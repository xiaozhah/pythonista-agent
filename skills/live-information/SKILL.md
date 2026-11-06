---
name: live-information
description: Use when the user asks about something current — weather, prices, exchange rates, news, sports, opening hours, the latest version of a package
---

Search snippets and cached pages are often days old. Get the answer from a live source, and check
its date against today's (in the system prompt).

1. **A public API, through run_python with requests** — fastest and exact. Ones that need no key:
   - Weather: `https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto`
     Place → coordinates: `https://geocoding-api.open-meteo.com/v1/search?name=Manchester&count=1`
     `weather_code` is a WMO code (0 clear, 1–3 partly cloudy to overcast, 45/48 fog, 51–67 rain,
     71–77 snow, 80–82 showers, 95+ thunderstorm).
   - Exchange rates: `https://open.er-api.com/v6/latest/USD`
   - Package versions: `https://pypi.org/pypi/<name>/json` (`info.version`)
2. **web_fetch a page** found by web_search, when there is no API: it reads the page as it is now.
   Prefer the official source (a national weather service, the project's own site).
3. **web_search alone** only for things that don't change by the day.

"Here" or "near me": the location tool gives the device's position (it asks the user first).
Say where the numbers came from and for what time.
