"""Erzeugt Kalender-Abos (.ics) aus den Urlaubsplaner-Daten in Firebase.

Läuft automatisch per GitHub Actions (.github/workflows/kalender.yml) und
schreibt kalender-p1.ics, kalender-p2.ics, kalender-p3.ics und kalender-alle.ics.
Nur Python-Standardbibliothek, keine Abhängigkeiten.
"""
import datetime
import json
import urllib.error
import urllib.request

PROJECT = "urlaubsplaner-2680f"
API_KEY = "AIzaSyDSUrp5woaoQir8jYswz2P5z1D-jzTuMr4"
YEAR = 2027
PEOPLE = ["p1", "p2", "p3"]
DEFAULT_NAMES = {"p1": "Person 1", "p2": "Person 2", "p3": "Kollegin"}

# Gesetzliche Feiertage Baden-Württemberg 2027, die auf Mo–Fr fallen
FEIERTAGE = {"01-01", "01-06", "03-26", "03-29", "05-06", "05-17", "05-27", "11-01"}

# Fester Zeitstempel, damit sich die Dateien nur ändern, wenn sich die Daten ändern
DTSTAMP = "20261119T000000Z"


def convert(value):
    """Firestore-REST-Werte in normale Python-Werte umwandeln."""
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "booleanValue" in value:
        return value["booleanValue"]
    if "mapValue" in value:
        return {k: convert(v) for k, v in value["mapValue"].get("fields", {}).items()}
    if "arrayValue" in value:
        return [convert(v) for v in value["arrayValue"].get("values", [])]
    return None


def load(pid):
    url = (f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)"
           f"/documents/personen/{pid}?key={API_KEY}")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            doc = json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return {}
        raise
    return {k: convert(v) for k, v in doc.get("fields", {}).items()}


def key(day):
    return day.strftime("%m-%d")


def main():
    data = {p: load(p) for p in PEOPLE}
    for p in PEOPLE:
        d = data[p]
        d.setdefault("name", DEFAULT_NAMES[p])
        d["name"] = d["name"] or DEFAULT_NAMES[p]
        d["tage"] = d.get("tage") or {}
        d["vertretung"] = d.get("vertretung") or {}
        d["arbeitstage"] = d.get("arbeitstage") or [1, 2, 3, 4, 5]

    def workday(day):
        return day.isoweekday() <= 5 and key(day) not in FEIERTAGE

    def covering(day):
        return workday(day) and key(day) in data["p3"]["tage"]

    def works(p, day):
        if not workday(day):
            return False
        d = data[p]
        return (day.isoweekday() in d["arbeitstage"] or key(day) in d["vertretung"]
                or (p == "p2" and covering(day)))

    def events(p):
        """Ganze Urlaubstage zu Blöcken zusammenfassen (über Wochenenden und freie Tage hinweg)."""
        d = data[p]
        out = []
        run_start = last_full = None
        day = datetime.date(YEAR, 1, 1)
        end = datetime.date(YEAR, 12, 31)
        while day <= end:
            mark = d["tage"].get(key(day)) if works(p, day) else None
            if mark == "ganz":
                run_start = run_start or day
                last_full = day
            elif works(p, day):
                if run_start:
                    out.append((run_start, last_full, False))
                    run_start = last_full = None
                if mark == "halb":
                    out.append((day, day, True))
            day += datetime.timedelta(days=1)
        if run_start:
            out.append((run_start, last_full, False))
        return out

    def vevents(p):
        name = data[p]["name"]
        lines = []
        for start, last, half in events(p):
            summary = f"Urlaub {name}" + (" (halber Tag)" if half else "")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{p}-{start:%Y%m%d}-{'halb' if half else 'ganz'}@urlaubsplaner",
                f"DTSTAMP:{DTSTAMP}",
                f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                f"DTEND;VALUE=DATE:{last + datetime.timedelta(days=1):%Y%m%d}",
                f"SUMMARY:{escape(summary)}",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        return lines

    def calendar(title, body):
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Urlaubsplaner//DE",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{escape(title)}",
            "X-WR-TIMEZONE:Europe/Berlin",
            "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
            "X-PUBLISHED-TTL:PT1H",
        ] + body + ["END:VCALENDAR"]
        return "\r\n".join(lines) + "\r\n"

    for p in PEOPLE:
        write(f"kalender-{p}.ics", calendar(f"Urlaub {data[p]['name']}", vevents(p)))
    alle = []
    for p in PEOPLE:
        alle += vevents(p)
    write("kalender-alle.ics", calendar("Urlaubsplaner 2027", alle))


def escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def write(name, content):
    with open(name, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    print("geschrieben:", name)


if __name__ == "__main__":
    main()
