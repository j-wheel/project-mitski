import re
from datetime import UTC, datetime, timedelta

import aiohttp

from mitski.brain.answers import keywords
from mitski.chat.messages import short_name
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import say, wording

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WMO = wording("thinking.weather_codes")


class Toolbox(Component):
    def __init__(self, app):
        super().__init__(app)
        self.places = {}

    @property
    def fahrenheit(self):
        return str(self.cfg.WEATHER_UNITS).lower().startswith(("imp", "f"))

    async def place(self, name):
        key = name.strip().lower()
        if key in self.places:
            return self.places[key]
        params = {"name": re.split(r",", name)[0].strip(), "count": 5, "language": "en", "format": "json"}
        async with self.app.http.get(GEO_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json(content_type=None) if r.status == 200 else {}
        results = data.get("results") or []
        if "," in name and results:
            hint = name.split(",", 1)[1].strip().lower()
            results = sorted(
                results,
                key=lambda p: (
                    hint not in f"{p.get('admin1', '')} {p.get('country', '')} {p.get('country_code', '')}".lower()
                ),
            )
        place = results[0] if results else None
        self.places[key] = place
        return place

    def _place_name(self, p):
        return ", ".join(
            x
            for x in (p.get("name"), p.get("admin1") if p.get("admin1") != p.get("name") else None, p.get("country"))
            if x
        )

    async def weather(self, where):
        p = await self.place(where)
        if not p:
            return say("thinking.weather_not_found", where=where)
        params = {
            "latitude": p["latitude"],
            "longitude": p["longitude"],
            "timezone": "auto",
            "forecast_days": 1,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        }
        if self.fahrenheit:
            params.update(temperature_unit="fahrenheit", wind_speed_unit="mph")
        async with self.app.http.get(FORECAST_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return ""
            data = await r.json(content_type=None)
        cur, day = data.get("current") or {}, data.get("daily") or {}
        unit = "°F" if self.fahrenheit else "°C"
        wind = "mph" if self.fahrenheit else "km/h"

        def first(key):
            v = day.get(key)
            return v[0] if isinstance(v, list) and v else None

        parts = []
        if cur.get("temperature_2m") is not None:
            parts.append(f"{round(cur['temperature_2m'])}{unit}")
            if (
                cur.get("apparent_temperature") is not None
                and abs(cur["apparent_temperature"] - cur["temperature_2m"]) >= 3
            ):
                parts.append(
                    say("thinking.weather_feels_like", temperature=round(cur["apparent_temperature"]), unit=unit)
                )
        if cur.get("weather_code") is not None:
            parts.append(WMO.get(int(cur["weather_code"]), "mixed weather"))
        if cur.get("wind_speed_10m") is not None and cur["wind_speed_10m"] >= 20:
            parts.append(say("thinking.weather_windy", speed=round(cur["wind_speed_10m"]), wind=wind))
        today = []
        if first("temperature_2m_min") is not None and first("temperature_2m_max") is not None:
            today.append(
                say(
                    "thinking.weather_range",
                    low=round(first("temperature_2m_min")),
                    high=round(first("temperature_2m_max")),
                    unit=unit,
                )
            )
        if (first("precipitation_probability_max") or 0) >= 30:
            today.append(say("thinking.weather_rain", percent=first("precipitation_probability_max")))
        local = ""
        if data.get("utc_offset_seconds") is not None:
            t = datetime.now(UTC) + timedelta(seconds=data["utc_offset_seconds"])
            local = say("thinking.weather_local_time", time=t.strftime("%H:%M"))
        if not parts:
            return ""
        return (
            say("thinking.weather", place=self._place_name(p), now=", ".join(parts))
            + (say("thinking.weather_today", today=", ".join(today)) if today else "")
            + f"{local}."
        )

    async def day_forecast(self, where, day):
        p = await self.place(where)
        if not p:
            return ""
        params = {
            "latitude": p["latitude"],
            "longitude": p["longitude"],
            "timezone": "auto",
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        }
        if self.fahrenheit:
            params["temperature_unit"] = "fahrenheit"
        async with self.app.http.get(FORECAST_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return ""
            daily = (await r.json(content_type=None)).get("daily") or {}

        def first(key):
            v = daily.get(key)
            return v[0] if isinstance(v, list) and v else None

        parts = []
        if first("weather_code") is not None:
            parts.append(WMO.get(int(first("weather_code")), "mixed weather"))
        if first("temperature_2m_min") is not None and first("temperature_2m_max") is not None:
            unit = "°F" if self.fahrenheit else "°C"
            parts.append(
                say(
                    "thinking.weather_range",
                    low=round(first("temperature_2m_min")),
                    high=round(first("temperature_2m_max")),
                    unit=unit,
                )
            )
        if (first("precipitation_probability_max") or 0) >= 30:
            parts.append(say("thinking.weather_rain", percent=first("precipitation_probability_max")))
        return ", ".join(parts)

    async def time_in(self, where):
        p = await self.place(where)
        if not p:
            return ""
        params = {
            "latitude": p["latitude"],
            "longitude": p["longitude"],
            "timezone": "auto",
            "current": "temperature_2m",
        }
        async with self.app.http.get(FORECAST_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return ""
            data = await r.json(content_type=None)
        if data.get("utc_offset_seconds") is None:
            return ""
        t = datetime.now(UTC) + timedelta(seconds=data["utc_offset_seconds"])
        mine = self.app.clock.now()
        diff = round((data["utc_offset_seconds"] - (mine.utcoffset() or timedelta()).total_seconds()) / 3600, 1)
        diff_text = (
            wording("thinking.time_same")
            if diff == 0
            else say("thinking.time_diff", hours=format(abs(diff), "g"), direction="ahead of" if diff > 0 else "behind")
        )
        return say("thinking.time", place=self._place_name(p), time=t.strftime("%A %H:%M"), difference=diff_text)

    async def history(self, what, channel, msgs):
        if not channel:
            return ""
        want = keywords(what)
        if not want:
            return ""
        seen = {m.id for m in msgs}
        people = {}
        for d in self.memory.people.values():
            for n in self.memory._names_of(d):
                people[str(n).lower()] = d
        old = [m for m in await self.app.context.history(channel, 400) if m.id not in seen]
        scored = []
        for m in old:
            text = self.messages.text(m)
            author = (self.memory.call_name(m.author) or short_name(m.author)).lower()
            score = len(want & keywords(text)) + (1.5 if author in want or short_name(m.author).lower() in want else 0)
            if score >= 1:
                scored.append((score, m))
        if not scored:
            return say("thinking.history_nothing", what=what)
        best = sorted(sorted(scored, key=lambda x: -x[0])[:6], key=lambda x: x[1].id)
        now = datetime.now(UTC)
        lines = []
        for _, m in best:
            mins = int((now - m.created_at).total_seconds() // 60)
            when = f"{mins} min ago" if mins < 60 else (f"{mins // 60}h ago" if mins < 1440 else f"{mins // 1440}d ago")
            who = "you" if m.author.id == self.me.id else (self.memory.call_name(m.author) or short_name(m.author))
            lines.append(f"{who} ({when}): {cut(self.messages.text(m), 160)}")
        return (wording("thinking.history_found") + "\n") + "\n".join(lines)

    def recall(self, who, skip_id=None):
        uid, d = self.memory.find_person(re.sub(r"^@", "", who))
        if d is None or (skip_id is not None and str(uid) == str(skip_id)):
            return ""
        call = self.memory.call_name(d) or d.get("name")
        bits = [b for b in [self.memory.slot_summary(d, public=True)] if b]
        bits += [
            f["text"] + ((" " + wording("thinking.recall_heard")) if f.get("src") in ("guess", "heard") else "")
            for f in self.memory.pick_facts(d, "", 4, public=True)
        ]
        return (say("thinking.recall", name=call) + " ") + "; ".join(bits) + "." if bits else ""
