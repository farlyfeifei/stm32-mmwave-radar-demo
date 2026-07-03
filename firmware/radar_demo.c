/*
 * STM32 mmWave radar target detection demo.
 *
 * This file is HAL-independent on purpose. In an STM32Cube project, feed UART
 * DMA/interrupt bytes into radar_parser_push_byte(), then call tracker_update()
 * when a frame is decoded.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define RADAR_FRAME_MAGIC_0 0xAAu
#define RADAR_FRAME_MAGIC_1 0x55u
#define RADAR_PROTOCOL_VERSION 1u
#define RADAR_MAX_TARGETS 8u
#define RADAR_MAX_TRACKS 6u
#define RADAR_PAYLOAD_BYTES_PER_TARGET 8u
#define RADAR_HEADER_BYTES 5u
#define RADAR_CRC_BYTES 2u
#define RADAR_FRAME_MAX_BYTES (RADAR_HEADER_BYTES + RADAR_MAX_TARGETS * RADAR_PAYLOAD_BYTES_PER_TARGET + RADAR_CRC_BYTES)

typedef struct {
    float range_m;
    float velocity_mps;
    float angle_deg;
    float snr_db;
} RadarMeasurement;

typedef struct {
    uint8_t seq;
    uint8_t count;
    RadarMeasurement items[RADAR_MAX_TARGETS];
} RadarFrame;

typedef struct {
    uint8_t id;
    uint8_t active;
    uint8_t age;
    uint8_t missed;
    float range_m;
    float velocity_mps;
    float angle_deg;
    float confidence;
} RadarTrack;

typedef struct {
    RadarTrack tracks[RADAR_MAX_TRACKS];
    uint8_t next_id;
} RadarTracker;

typedef struct {
    uint8_t buffer[RADAR_FRAME_MAX_BYTES];
    uint16_t length;
    uint16_t expected_length;
} RadarParser;

static uint16_t crc16_ccitt(const uint8_t *data, uint16_t length)
{
    uint16_t crc = 0xFFFFu;
    for (uint16_t i = 0; i < length; ++i) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t bit = 0; bit < 8; ++bit) {
            if ((crc & 0x8000u) != 0u) {
                crc = (uint16_t)((crc << 1) ^ 0x1021u);
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

static int16_t read_i16_le(const uint8_t *p)
{
    return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint16_t read_u16_le(const uint8_t *p)
{
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

void radar_parser_init(RadarParser *parser)
{
    memset(parser, 0, sizeof(*parser));
}

static uint8_t decode_frame(const uint8_t *raw, uint16_t length, RadarFrame *out)
{
    if (length < RADAR_HEADER_BYTES + RADAR_CRC_BYTES) {
        return 0u;
    }
    if (raw[0] != RADAR_FRAME_MAGIC_0 || raw[1] != RADAR_FRAME_MAGIC_1) {
        return 0u;
    }
    if (raw[2] != RADAR_PROTOCOL_VERSION || raw[4] > RADAR_MAX_TARGETS) {
        return 0u;
    }

    const uint16_t expected = (uint16_t)(RADAR_HEADER_BYTES + raw[4] * RADAR_PAYLOAD_BYTES_PER_TARGET + RADAR_CRC_BYTES);
    if (length != expected) {
        return 0u;
    }

    const uint16_t received_crc = read_u16_le(&raw[length - RADAR_CRC_BYTES]);
    const uint16_t calculated_crc = crc16_ccitt(raw, (uint16_t)(length - RADAR_CRC_BYTES));
    if (received_crc != calculated_crc) {
        return 0u;
    }

    out->seq = raw[3];
    out->count = raw[4];
    for (uint8_t i = 0; i < out->count; ++i) {
        const uint8_t *target = &raw[RADAR_HEADER_BYTES + i * RADAR_PAYLOAD_BYTES_PER_TARGET];
        out->items[i].range_m = (float)read_i16_le(&target[0]) / 100.0f;
        out->items[i].velocity_mps = (float)read_i16_le(&target[2]) / 100.0f;
        out->items[i].angle_deg = (float)read_i16_le(&target[4]) / 100.0f;
        out->items[i].snr_db = (float)read_u16_le(&target[6]) / 256.0f;
    }

    return 1u;
}

uint8_t radar_parser_push_byte(RadarParser *parser, uint8_t byte, RadarFrame *out)
{
    if (parser->length == 0u && byte != RADAR_FRAME_MAGIC_0) {
        return 0u;
    }
    if (parser->length == 1u && byte != RADAR_FRAME_MAGIC_1) {
        parser->length = 0u;
        return 0u;
    }

    parser->buffer[parser->length++] = byte;

    if (parser->length == RADAR_HEADER_BYTES) {
        const uint8_t count = parser->buffer[4];
        if (parser->buffer[2] != RADAR_PROTOCOL_VERSION || count > RADAR_MAX_TARGETS) {
            parser->length = 0u;
            return 0u;
        }
        parser->expected_length = (uint16_t)(RADAR_HEADER_BYTES + count * RADAR_PAYLOAD_BYTES_PER_TARGET + RADAR_CRC_BYTES);
    }

    if (parser->expected_length > 0u && parser->length >= parser->expected_length) {
        const uint16_t frame_length = parser->expected_length;
        parser->length = 0u;
        parser->expected_length = 0u;
        return decode_frame(parser->buffer, frame_length, out);
    }

    if (parser->length >= RADAR_FRAME_MAX_BYTES) {
        parser->length = 0u;
        parser->expected_length = 0u;
    }
    return 0u;
}

void tracker_init(RadarTracker *tracker)
{
    memset(tracker, 0, sizeof(*tracker));
    tracker->next_id = 1u;
}

static float absf(float value)
{
    return value < 0.0f ? -value : value;
}

static float measurement_distance(const RadarTrack *track, const RadarMeasurement *measurement)
{
    const float range_error = absf(track->range_m - measurement->range_m);
    const float angle_error = absf(track->angle_deg - measurement->angle_deg) * 0.05f;
    const float velocity_error = absf(track->velocity_mps - measurement->velocity_mps) * 0.4f;
    return range_error + angle_error + velocity_error;
}

static RadarTrack *allocate_track(RadarTracker *tracker)
{
    for (uint8_t i = 0; i < RADAR_MAX_TRACKS; ++i) {
        if (tracker->tracks[i].active == 0u) {
            tracker->tracks[i].id = tracker->next_id++;
            if (tracker->next_id == 0u) {
                tracker->next_id = 1u;
            }
            tracker->tracks[i].active = 1u;
            tracker->tracks[i].age = 0u;
            tracker->tracks[i].missed = 0u;
            return &tracker->tracks[i];
        }
    }
    return NULL;
}

static void update_track(RadarTrack *track, const RadarMeasurement *measurement)
{
    const float alpha = 0.35f;
    track->range_m = alpha * measurement->range_m + (1.0f - alpha) * track->range_m;
    track->velocity_mps = alpha * measurement->velocity_mps + (1.0f - alpha) * track->velocity_mps;
    track->angle_deg = alpha * measurement->angle_deg + (1.0f - alpha) * track->angle_deg;
    track->confidence = alpha * measurement->snr_db + (1.0f - alpha) * track->confidence;
    track->age++;
    track->missed = 0u;
}

uint8_t tracker_update(RadarTracker *tracker, const RadarFrame *frame)
{
    uint8_t matched_tracks[RADAR_MAX_TRACKS] = {0};
    uint8_t stable_count = 0u;

    for (uint8_t t = 0; t < RADAR_MAX_TRACKS; ++t) {
        if (tracker->tracks[t].active != 0u) {
            tracker->tracks[t].missed++;
            if (tracker->tracks[t].missed > 5u) {
                tracker->tracks[t].active = 0u;
            }
        }
    }

    for (uint8_t i = 0; i < frame->count; ++i) {
        const RadarMeasurement *measurement = &frame->items[i];
        if (measurement->snr_db < 8.0f || measurement->range_m < 0.3f || measurement->range_m > 80.0f) {
            continue;
        }

        uint8_t best_index = RADAR_MAX_TRACKS;
        float best_score = 2.5f;
        for (uint8_t t = 0; t < RADAR_MAX_TRACKS; ++t) {
            if (tracker->tracks[t].active == 0u || matched_tracks[t] != 0u) {
                continue;
            }
            const float score = measurement_distance(&tracker->tracks[t], measurement);
            if (score < best_score) {
                best_score = score;
                best_index = t;
            }
        }

        RadarTrack *track = NULL;
        if (best_index < RADAR_MAX_TRACKS) {
            track = &tracker->tracks[best_index];
            matched_tracks[best_index] = 1u;
        } else {
            track = allocate_track(tracker);
        }

        if (track != NULL) {
            if (track->age == 0u && track->confidence == 0.0f) {
                track->range_m = measurement->range_m;
                track->velocity_mps = measurement->velocity_mps;
                track->angle_deg = measurement->angle_deg;
                track->confidence = measurement->snr_db;
                track->age = 1u;
                track->missed = 0u;
            } else {
                update_track(track, measurement);
            }
        }
    }

    for (uint8_t t = 0; t < RADAR_MAX_TRACKS; ++t) {
        if (tracker->tracks[t].active != 0u && tracker->tracks[t].age >= 3u && tracker->tracks[t].confidence >= 10.0f) {
            stable_count++;
        }
    }

    return stable_count;
}

#ifdef RADAR_DEMO_SELF_TEST
static void write_u16_le(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)(value & 0xFFu);
    p[1] = (uint8_t)(value >> 8);
}

static uint16_t build_test_frame(uint8_t *out)
{
    out[0] = RADAR_FRAME_MAGIC_0;
    out[1] = RADAR_FRAME_MAGIC_1;
    out[2] = RADAR_PROTOCOL_VERSION;
    out[3] = 42u;
    out[4] = 1u;
    write_u16_le(&out[5], 1234u);
    write_u16_le(&out[7], 80u);
    write_u16_le(&out[9], (uint16_t)(int16_t)-530);
    write_u16_le(&out[11], (uint16_t)(18u * 256u));
    const uint16_t crc = crc16_ccitt(out, 13u);
    write_u16_le(&out[13], crc);
    return 15u;
}

int main(void)
{
    RadarParser parser;
    RadarFrame frame;
    RadarTracker tracker;
    uint8_t raw[RADAR_FRAME_MAX_BYTES];
    const uint16_t length = build_test_frame(raw);

    radar_parser_init(&parser);
    tracker_init(&tracker);

    for (uint16_t i = 0; i < length; ++i) {
        if (radar_parser_push_byte(&parser, raw[i], &frame) != 0u) {
            const uint8_t stable = tracker_update(&tracker, &frame);
            printf("frame=%u targets=%u stable=%u range=%.2fm velocity=%.2fm/s angle=%.2fdeg\n",
                   frame.seq,
                   frame.count,
                   stable,
                   frame.items[0].range_m,
                   frame.items[0].velocity_mps,
                   frame.items[0].angle_deg);
        }
    }
    return 0;
}
#endif
