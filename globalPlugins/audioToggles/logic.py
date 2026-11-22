# -*- coding: UTF-8 -*-
# AudioToggles - pure helper logic. No NVDA or Windows imports, so it can be unit tested anywhere.

import json


def shorten_names(names):
	"""Shorten 'Speakers (Realtek Audio)' to 'Speakers', unless that would make names ambiguous."""
	bases = [(name.split(" (")[0].strip() or name) for name in names]
	return [base if bases.count(base) == 1 else name for base, name in zip(bases, names)]


def next_device(devices, current_id, skipped):
	"""Next device after current_id, ignoring skipped ids. None if every device is skipped."""
	candidates = [device for device in devices if device.id not in skipped]
	if not candidates:
		return None
	ids = [device.id for device in candidates]
	if current_id in ids:
		return candidates[(ids.index(current_id) + 1) % len(candidates)]
	return candidates[0]


def diff_snapshots(old, new):
	"""Compare two {(flow, id): name} dicts and list ('added'|'removed', flow, id, name)."""
	events = []
	for key in sorted(new):
		if key not in old:
			events.append(("added", key[0], key[1], new[key]))
	for key in sorted(old):
		if key not in new:
			events.append(("removed", key[0], key[1], old[key]))
	return events


def parse_presets(raw):
	"""Parse stored preset JSON, discarding anything malformed."""
	try:
		data = json.loads(raw or "[]")
	except (TypeError, ValueError):
		return []
	if not isinstance(data, list):
		return []
	return [item for item in data if isinstance(item, dict) and item.get("name")]


def dump_presets(presets):
	return json.dumps(presets, ensure_ascii=False)


def clamp(value, low, high):
	return max(low, min(high, value))
