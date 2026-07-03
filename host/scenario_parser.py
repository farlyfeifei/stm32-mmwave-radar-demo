"""Chinese natural-language flight-description parser for the radar demo.

Converts Chinese text like "两个目标从远处飞来,一个从左,一个从右,强杂波"
into a ScenarioConfig that can be fed to generate_scenario_from_config.

Usage:
    from host.scenario_parser import parse_flight_description, build_config_from_text
    cfg = build_config_from_text("单目标高速接近,弱信号,无杂波")
    # cfg is a ScenarioConfig; pass its targets to generate_scenario_from_config
"""

from __future__ import annotations

import re
from typing import List, Optional

from host.radar_demo import ClutterSpec, ScenarioConfig, TargetSpec


# ---- Chinese number parsing ----
_CN_NUM = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

def _parse_cn_count(s: str) -> Optional[int]:
    """Extract a count (1-8) from Chinese or Arabic numerals in text."""
    # Arabic: "2个目标", "3架"
    m = re.search(r"(\d)\s*[个架项目]", s)
    if m:
        return min(8, int(m.group(1)))
    # Chinese with explicit counter: "两个目标", "三架", "四个"
    # Must match the pattern <num><counter> to avoid false positives like "一个从左"
    m2 = re.search(r"(零|一|两|二|三|四|五|六|七|八|九|十)\s*[个架项目]", s)
    if m2:
        cn = m2.group(1)
        if cn == "十":
            return 10
        return min(8, _CN_NUM.get(cn, 1))
    # Word-based: "单目标", "双目标", "编队"
    if re.search(r"(单目标|单个|single)", s, re.I):
        return 1
    if re.search(r"(双目标|双个|pair|dual)", s, re.I):
        return 2
    return None


# ---- Speed parsing ----
def _parse_speed(text: str, default: float = -0.4) -> float:
    """Extract speed in m/s. Negative = approaching (toward radar)."""
    # "X米每秒" / "X m/s"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:米每秒|m/s|ms)", text, re.I)
    if m:
        speed = float(m.group(1))
        return -speed if re.search(r"(接近|飞来|靠近|coming|approach)", text, re.I) else speed
    # Qualitative
    if re.search(r"(高速|快速|rapid|fast)", text, re.I):
        return -0.8
    if re.search(r"(慢速|缓慢|slow)", text, re.I):
        return -0.2
    if re.search(r"(悬停|静止|hover|still)", text, re.I):
        return 0.0
    if re.search(r"(远离|飞走|背离|leav|depart|away)", text, re.I):
        return 0.5
    if re.search(r"(接近|飞来|靠近|approach|incoming)", text, re.I):
        return -0.4
    return default


# ---- Range parsing ----
def _parse_range(text: str, default: float = 18.0) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:米|m)\b", text)
    if m and ("距离" in text or "远处" in text or "近处" in text or "起始" in text):
        return float(m.group(1))
    if re.search(r"(远处|远距|far|distant)", text, re.I):
        return 25.0
    if re.search(r"(近处|近距|close|near)", text, re.I):
        return 8.0
    return default


# ---- Angle parsing ----
def _parse_angle(text: str, default: float = 0.0) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*度", text)
    if m:
        val = float(m.group(1))
        if re.search(r"(左|left)", text, re.I):
            return -val
        return val
    if re.search(r"(左侧|从左|左方|left)", text, re.I):
        return -12.0
    if re.search(r"(右侧|从右|右方|right)", text, re.I):
        return 12.0
    if re.search(r"(正前|正中|中央|center)", text, re.I):
        return 0.0
    return default


# ---- Angle rate (turning) ----
def _parse_angle_rate(text: str, default: float = 0.0) -> float:
    if re.search(r"(左转|向左转|turn left)", text, re.I):
        return -1.5
    if re.search(r"(右转|向右转|turn right)", text, re.I):
        return 1.5
    if re.search(r"(转弯|转向|机动|盘旋|circle|turn)", text, re.I):
        return 1.0
    return default


# ---- SNR parsing ----
def _parse_snr(text: str, default: float = 15.0) -> float:
    if re.search(r"(弱信号|低信号|weak|faint)", text, re.I):
        return 9.5
    if re.search(r"(强信号|高信号|strong)", text, re.I):
        return 19.0
    return default


# ---- Clutter parsing ----
def _parse_clutter(text: str) -> ClutterSpec:
    if re.search(r"(无杂波|干净|清空|no clutter|clean)", text, re.I):
        return ClutterSpec(every=0)
    if re.search(r"(强杂波|密集干扰|heavy clutter|storm)", text, re.I):
        return ClutterSpec(every=4, snr_min=4.0, snr_max=9.0)
    if re.search(r"(弱杂波|轻微干扰|light clutter)", text, re.I):
        return ClutterSpec(every=15, snr_min=3.0, snr_max=6.0)
    # Default: medium
    return ClutterSpec(every=9)


# ---- Dropout parsing ----
def _parse_dropout(text: str) -> int:
    if re.search(r"(频繁丢|频繁漏|frequent.*drop)", text, re.I):
        return 8
    if re.search(r"(偶尔丢|偶尔漏|occasional.*drop)", text, re.I):
        return 20
    if re.search(r"(稳定信号|不丢|no drop|stable)", text, re.I):
        return 0
    return 0  # default: no dropout


def _parse_noise(text: str) -> dict:
    if re.search(r"(高噪声|强噪声|noisy)", text, re.I):
        return {"range": 0.15, "velocity": 0.08, "angle": 0.5, "snr": 2.0}
    if re.search(r"(低噪声|clean signal)", text, re.I):
        return {"range": 0.04, "velocity": 0.02, "angle": 0.15, "snr": 0.5}
    return {"range": 0.08, "velocity": 0.04, "angle": 0.3, "snr": 1.0}


# ---- Main parser ----
def parse_flight_description(text: str) -> ScenarioConfig:
    """Parse a Chinese flight description into a ScenarioConfig.

    Recognized keywords:
      Count:    一个/两个/三个/四个目标, 单目标, 双目标, 编队
      Motion:   接近/飞来/靠近, 远离/飞走, 悬停/静止, 高速, 慢速
      Range:    远处, 近处, X米
      Angle:    左侧/从左, 右侧/从右, 正前方, X度
      Turn:     左转, 右转, 转弯, 盘旋, 机动
      Signal:   强信号, 弱信号
      Clutter:  无杂波/干净, 弱杂波, 强杂波/密集干扰
      Dropout:  频繁丢, 偶尔丢, 稳定信号
      Noise:    高噪声, 低噪声
    """
    if not text or not text.strip():
        return _default_config()

    t = text.strip()

    # Determine target count
    count = _parse_cn_count(t)
    if count is None:
        if re.search(r"(编队|formation)", t, re.I):
            count = 3
        elif re.search(r"(单|single|一个)", t, re.I):
            count = 1
        elif re.search(r"(双|pair|两个)", t, re.I):
            count = 2
        else:
            count = 1  # default single target

    # Shared parameters
    speed = _parse_speed(t)
    range_start = _parse_range(t)
    angle_rate = _parse_angle_rate(t)
    snr = _parse_snr(t)
    dropout = _parse_dropout(t)
    noise = _parse_noise(t)
    clutter = _parse_clutter(t)

    # Build targets
    targets: List[TargetSpec] = []

    if count == 1:
        targets.append(TargetSpec(
            range_start_m=range_start,
            velocity_mps=speed,
            angle_start_deg=_parse_angle(t),
            angle_rate_dps=angle_rate,
            snr_db=snr,
            dropout_every=dropout,
            noise_range=noise["range"],
            noise_velocity=noise["velocity"],
            noise_angle=noise["angle"],
            noise_snr=noise["snr"],
        ))
    elif count == 2:
        # Two targets from opposite sides
        targets.append(TargetSpec(
            range_start_m=range_start,
            velocity_mps=speed,
            angle_start_deg=-_parse_angle(t, 12.0) if _parse_angle(t) == 0 else _parse_angle(t),
            angle_rate_dps=angle_rate if angle_rate != 0 else 1.0,
            snr_db=snr,
            dropout_every=dropout,
            noise_range=noise["range"],
            noise_velocity=noise["velocity"],
            noise_angle=noise["angle"],
            noise_snr=noise["snr"],
        ))
        targets.append(TargetSpec(
            range_start_m=range_start - 4.0,
            velocity_mps=-speed * 0.7 if speed != 0 else 0.3,
            angle_start_deg=-targets[0].angle_start_deg,
            angle_rate_dps=-targets[0].angle_rate_dps,
            snr_db=snr - 2.0,
            start_frame=10,
            dropout_every=dropout if dropout else 23,
            noise_range=noise["range"],
            noise_velocity=noise["velocity"],
            noise_angle=noise["angle"],
            noise_snr=noise["snr"],
        ))
    else:
        # Formation: count targets spread in angle
        spread = 8.0
        for i in range(count):
            offset = (i - (count - 1) / 2) * spread
            targets.append(TargetSpec(
                range_start_m=range_start + (i % 2) * 1.5,
                velocity_mps=speed,
                angle_start_deg=offset,
                angle_rate_dps=angle_rate * 0.3,
                snr_db=snr - i * 0.5,
                dropout_every=dropout if dropout else (29 + i * 7),
                noise_range=noise["range"],
                noise_velocity=noise["velocity"],
                noise_angle=noise["angle"],
                noise_snr=noise["snr"],
            ))

    return ScenarioConfig(
        name="交互场景",
        description=text[:60],
        frame_count=200,
        frame_interval_s=0.08,
        targets=targets,
        clutter=clutter,
    )


def _default_config() -> ScenarioConfig:
    return ScenarioConfig(
        name="默认场景",
        description="单目标匀速接近",
        frame_count=160,
        frame_interval_s=0.08,
        targets=[TargetSpec(range_start_m=18.0, velocity_mps=-0.4, angle_start_deg=0.0, snr_db=16.0)],
        clutter=ClutterSpec(every=0),
    )


# ---- Preset examples for the UI ----
EXAMPLES = [
    "单目标高速接近,强信号,无杂波",
    "两个目标从远处飞来,一个从左一个从右,中等杂波",
    "三目标编队缓慢接近,弱杂波",
    "单目标悬停,弱信号,强杂波",
    "单目标右转弯机动,强信号,无杂波",
    "双目标对飞交叉,频繁丢目标,高噪声",
    "单目标从近处远离,低噪声,弱杂波",
]


def explain(cfg: ScenarioConfig) -> str:
    """Generate a readable explanation of the parsed scenario."""
    lines = ["【飞行场景解析】"]
    lines.append(f"  目标数: {len(cfg.targets)}")
    for i, t in enumerate(cfg.targets):
        direction = "接近" if t.velocity_mps < 0 else ("远离" if t.velocity_mps > 0 else "悬停")
        lines.append(
            f"  目标{i+1}: {t.range_start_m:.0f}m {direction} {abs(t.velocity_mps):.2f}m/s "
            f"角度{t.angle_start_deg:+.0f}° SNR {t.snr_db:.0f}dB"
        )
        if t.angle_rate_dps != 0:
            turn = "左转" if t.angle_rate_dps < 0 else "右转"
            lines.append(f"         {turn} {abs(t.angle_rate_dps):.1f}°/s")
        if t.dropout_every:
            lines.append(f"         每{t.dropout_every}帧漏检一次")
    if cfg.clutter.every:
        lines.append(f"  杂波: 每{cfg.clutter.every}帧注入 (SNR {cfg.clutter.snr_min:.0f}-{cfg.clutter.snr_max:.0f}dB)")
    else:
        lines.append("  杂波: 无")
    lines.append(f"  总帧数: {cfg.frame_count}")
    return "\n".join(lines)
