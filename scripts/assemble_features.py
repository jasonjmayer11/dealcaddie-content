#!/usr/bin/env python3
"""Investor feature-tour reel: "everything in one analysis".

Usage: python3 scripts/assemble_features.py <workdir> <out.mp4>
Reads data.json + card_*.png + photo.jpg written by record_features.js.

Beats (same look and motion as the daily reel, via reelkit):
  1. listing photo        city · price · specs · "We ran every strategy."
  2. CASH FLOW BY STRATEGY  animated list of all 7 strategies, best one highlighted
  3. COMPS                 49% below recent sales nearby   + Recently Sold card
  4. FINANCING SCENARIOS   $22,500 less cash to close      + scenarios table
  5. MAX OFFER             $210K                            + max offer card
  6. SHARE                 "Send the whole deal in one link." + the page a recipient sees
  7. end card
Any beat whose data or card is missing is skipped.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reelkit import *          # noqa: F401,F403
import reelkit as rk

work, out_mp4 = sys.argv[1], sys.argv[2]
rk.init(work)
os.environ.setdefault("MUSIC_VARIANT", "2")
out_dir = os.path.dirname(os.path.abspath(out_mp4))
d = json.load(open(os.path.join(work, "data.json")))
has = lambda f: os.path.exists(P(f))

city_line = d.get("cityLine") or ""
city = city_line.split(",")[0].strip()
place_ = re.sub(r"\s*\d{5}(-\d{4})?$", "", city_line).strip()
plural = lambda n, w: f"{n} {w}" + ("" if str(n) in ("1", "1.0") else "s")
specs = "  ·  ".join(x for x in [
    plural(d["beds"], "bed") if d.get("beds") else None,
    plural(d["baths"], "bath") if d.get("baths") else None,
    f"{d['sqft']} sq ft" if d.get("sqft") else None] if x)

timeline, says = [], []
hook = {"eyebrow": place_.upper() or "ACTIVE LISTING", "value": d.get("price") or "This house",
        "specs": specs, "sub": "We ran every strategy."}
timeline.append((render_photo_beat(hook, 3.8), 3.8))

# ---- 2. strategies ----
NAMES = [("LTR", "Long-term rental"), ("MTR", "Mid-term rental"), ("STR", "Short-term · Airbnb"),
         ("S8", "Section 8"), ("HH", "House hack"), ("BRRRR", "BRRRR"), ("FLIP", "Fix & flip · profit")]
strat = d.get("strategies") or {}
rows = []
for k, label in NAMES:
    v = strat.get(k)
    if not v:
        continue
    n = num(v.replace("k", "000").replace("K", "000"))
    rows.append({"label": label, "value": pretty_money(v.replace("k", "K")) + ("" if k == "FLIP" else "/mo"),
                 "color": GREEN if (n or 0) > 0 else RED, "_n": n, "_k": k})
monthly = [r for r in rows if r["_k"] != "FLIP"]
if monthly:
    best = max(monthly, key=lambda r: r["_n"] or -1e9)
    if (best["_n"] or 0) > 0:
        best["best"] = True
        says.append(f"Best play: {best['label'].lower()} at {best['value']}.")
if len(rows) >= 4:
    timeline.append((render_list_beat({"eyebrow": "CASH FLOW BY STRATEGY",
                                       "headline": f"{len(rows)} strategies. One tap.",
                                       "rows": rows}, 5.2), 5.2))

# ---- 3. comps ----
if has("card_comps.png"):
    pct, direc = d.get("compsPct"), (d.get("compsDir") or "below").lower()
    below = direc in ("below", "under")
    n = d.get("compCount")
    if pct:
        spec = {"eyebrow": "COMPARABLE SALES", "value": f"{pct}%", "unit": "", "color": GREEN if below else RED,
                "sub": f"{'below' if below else 'above'} what similar homes nearby sold for."}
        says.append(f"Priced {pct}% {'below' if below else 'above'} recent sales nearby.")
    else:
        spec = {"eyebrow": "COMPARABLE SALES", "headline": "Recent sales, pulled for you.",
                "sub": f"{n} nearby sales with $/sq ft." if n else "Nearby sales with $/sq ft."}
    spec.update({"card": "comps", "card_max_h": 600})
    timeline.append((render_stat_beat(spec, 3.8), 3.8))

# ---- 4. scenarios ----
if has("card_scen.png") and d.get("scenSaving"):
    a, b = d.get("scenDownA"), d.get("scenDownB")
    sub = f"less cash to close at {b} down vs {a}." if a and b else "less cash to close with Option B."
    timeline.append((render_stat_beat({"eyebrow": "FINANCING SCENARIOS", "value": f"${d['scenSaving']}", "unit": "",
                                       "color": GREEN, "sub": sub, "card": "scen", "crop": d.get("scenCrop"),
                                       "card_max_h": 700}, 3.8), 3.8))
    says.append(f"{b} down instead of {a}: ${d['scenSaving']} less cash to close." if a and b else "")

# ---- 5. max offer ----
if has("card_maxoffer.png") and d.get("maxOffer"):
    tgt = d.get("maxOfferTarget")
    sub = f"The most you can pay and still clear ${tgt}/mo." if tgt else "The most you can pay for your target return."
    timeline.append((render_stat_beat({"eyebrow": "MAX OFFER", "value": short_price(d["maxOffer"]), "unit": "",
                                       "color": INK, "sub": sub, "card": "maxoffer"}, 3.8), 3.8))
    says.append(f"Max offer: {short_price(d['maxOffer'])}.")

# ---- 6. share ----
if has("card_share.png"):
    timeline.append((render_stat_beat({"eyebrow": "SHARE", "headline": "Send the whole deal in one link.",
                                       "sub": "Your partner opens it on their phone. No login.",
                                       "card": "share", "crop": 0.66, "card_max_h": 720}, 3.8), 3.8))
    says.append("Shared the whole thing in one link.")

timeline.append((render_end_beat(3.6, line="Every strategy. One analysis.",
                                 sub="Comps, scenarios and max offer, in seconds."), 3.6))
encode(timeline, out_mp4)

Image.open(P("beat1.png")).save(os.path.join(out_dir, "cover.jpg"), quality=92)
title = [f"{short_price(d.get('price')) or 'This'} {city} house." if city else "This house.", "We ran every strategy."]
city_tag = "#" + re.sub(r"[^a-z]", "", city.lower()) + "realestate" if city else "#realestatedeals"
caption = f"""{' '.join(title)}

One paste of the Zillow link: long-term, mid-term, Airbnb, Section 8, house hack, BRRRR and flip, side by side. {' '.join(s for s in says if s)}

Comps, financing scenarios and your max offer in the same analysis — then send it in one link.

Try it free · dealcaddie.ai

#realestateinvesting #rentalproperty #cashflow #realestateinvestor {city_tag}
"""
open(os.path.join(out_dir, "caption.txt"), "w").write(caption)
json.dump({"hook": title, "beats": len(timeline), "duration": round(duration(out_mp4), 1), **d},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
print(f"built {out_mp4} ({duration(out_mp4):.1f}s, beats={len(timeline)})")
