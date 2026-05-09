"""ZWO service: genera file .zwo compatibili con MyWhoosh/Zwift."""
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

_AUTO_NOTE = (
    "⚠️ Importare in MyWhoosh Workout Builder web, "
    "correggere FTP a 202W e peso a 75kg prima di esportare su MyWhoosh."
)


def safe_filename(name: str) -> str:
    """Restituisce un nome file sicuro per il .zwo."""
    clean = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')
    return clean or "Workout"


def generate_zwo_xml(workout: dict, ftp: int, weight_kg: float = 75.0) -> str:
    """
    Genera XML .zwo standard da un dict workout strutturato.
    Duration sempre in secondi. Power come frazione di FTP (es. 0.70).
    """
    root = ET.Element("workout_file")

    ET.SubElement(root, "author").text = "Ambrofit"
    ET.SubElement(root, "name").text = workout.get("name", "Workout")
    base_desc = workout.get("description", "")
    ET.SubElement(root, "description").text = f"{base_desc}\n\n{_AUTO_NOTE}".strip()
    ET.SubElement(root, "sportType").text = "bike"
    ET.SubElement(root, "tags")

    workout_el = ET.SubElement(root, "workout")

    for seg in workout.get("segments", []):
        seg_type = seg.get("type", "SteadyState")
        duration_sec = int(round(float(seg.get("duration_min", 0)) * 60))

        if seg_type == "Warmup":
            el = ET.SubElement(workout_el, "Warmup")
            el.set("Duration", str(duration_sec))
            el.set("PowerLow", str(round(float(seg.get("power_low", 0.40)), 2)))
            el.set("PowerHigh", str(round(float(seg.get("power_high", 0.75)), 2)))

        elif seg_type == "Cooldown":
            el = ET.SubElement(workout_el, "Cooldown")
            el.set("Duration", str(duration_sec))
            el.set("PowerHigh", str(round(float(seg.get("power_high", 0.55)), 2)))
            el.set("PowerLow", str(round(float(seg.get("power_low", 0.35)), 2)))

        elif seg_type == "SteadyState":
            el = ET.SubElement(workout_el, "SteadyState")
            el.set("Duration", str(duration_sec))
            el.set("Power", str(round(float(seg.get("power", 0.70)), 2)))

        elif seg_type == "IntervalsT":
            el = ET.SubElement(workout_el, "IntervalsT")
            el.set("Repeat", str(int(seg.get("repeat", 4))))
            on_sec = int(round(float(seg.get("on_duration_min", 1)) * 60))
            off_sec = int(round(float(seg.get("off_duration_min", 1)) * 60))
            el.set("OnDuration", str(on_sec))
            el.set("OffDuration", str(off_sec))
            el.set("OnPower", str(round(float(seg.get("on_power", 1.0)), 2)))
            el.set("OffPower", str(round(float(seg.get("off_power", 0.55)), 2)))

        else:
            # Fallback: SteadyState
            el = ET.SubElement(workout_el, "SteadyState")
            el.set("Duration", str(duration_sec))
            el.set("Power", str(round(float(seg.get("power", 0.65)), 2)))

    # Pretty-print
    raw = ET.tostring(root, encoding="unicode")
    reparsed = minidom.parseString(raw)
    return reparsed.toprettyxml(indent="  ", encoding=None).replace(
        '<?xml version="1.0" ?>',
        '<?xml version="1.0" encoding="UTF-8"?>'
    )
