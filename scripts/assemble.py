#!/usr/bin/env python3
"""Assemble a DealCaddie Deal Verdict reel — "product" style.

Usage: python3 scripts/assemble.py <workdir> <out.mp4>
Reads photo.jpg, card_*.png and data.json from <workdir>.
Writes the 1080x1920 MP4, caption.txt, cover.jpg and meta.json next to it.

Design language (borrowed from Zillow / Airbnb / fintech product social):
  - one calm canvas (warm off-white), real brand logo, Inter type, no text boxes
  - every beat = small caps eyebrow + one big number + one quiet sub line + the real UI card as proof
  - everything centred on x=540 and inside the Reels safe area (y 290–1420)
  - motion is eased: elements rise + fade in on a stagger, numbers count up, card settles, slow drift
  - frames are rendered one by one in PIL and piped to ffmpeg (no zoompan jitter)

Beats (~3.8s each — enough time to read every number):
  1. listing photo, full bleed: city · price · hook question
  2. DEAL SCORE        6.9/10      + property card
  3. CASH FLOW         +$33/mo     + cash-flow card
  4. MAX OFFER $171K  (or the strategy that works, or CoC)  + its card
  5. logo + "Analyze any rental in seconds." + dealcaddie.ai button
"""
import json, math, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reelkit import *          # noqa: F401,F403  (shared look + motion)
import reelkit as rk

work, out_mp4 = sys.argv[1], sys.argv[2]
rk.init(work)
out_dir = os.path.dirname(os.path.abspath(out_mp4))
data = json.load(open(os.path.join(work, "data.json")))
AUDIENCE = (os.environ.get("AUDIENCE") or "investor").lower()   # "investor" (AM slot) or "agent" (PM slot)
AGENT = AUDIENCE == "agent"
AGENT_PRICE = os.environ.get("AGENT_PRICE") or "$39.99/mo"
os.environ.setdefault("MUSIC_VARIANT", "1" if AGENT else "0")


def pick_copy(d):
    pt = (d.get("propType") or "").lower()
    pt = {"quadplex": "fourplex", "2-unit": "duplex", "3-unit": "triplex", "4-unit": "fourplex"}.get(pt, pt)
    city_line = d.get("cityLine") or ""
    city = city_line.split(",")[0].strip()
    place = re.sub(r"\s*\d{5}(-\d{4})?$", "", city_line).strip()          # "Indianapolis, IN"
    price_full = d.get("price") or ""
    cf_s = d.get("ltrCashflow") or ""
    cf = num(cf_s)
    score = d.get("score")
    score_s = (score[:-2] if score and score.endswith(".0") else score) or None
    asking = num(price_full)

    if cf is not None and cf >= 200:
        q, cf_sub = "Guess the cash flow.", "After mortgage, taxes, insurance and reserves."
    elif cf is not None and cf < 0:
        q, cf_sub = "Looks like a deal. Is it?", "After mortgage, taxes, insurance and reserves."
    else:
        q, cf_sub = "Does it cash flow?", "Positive, but thin after every expense."
    if AGENT:
        q = "Your client asks: is it a deal?"
        cf_sub = ("Rent, taxes and insurance already pulled." if cf is not None and cf >= 200 else
                  "Thin. Your client should know before they offer." if cf is not None and cf >= 0 else
                  "Your client would lose money as a long-term rental.")

    plural = lambda n, w: f"{n} {w}" + ("" if str(n) in ("1", "1.0") else "s")
    specs = "  ·  ".join(x for x in [
        plural(d["beds"], "bed") if d.get("beds") else None,
        plural(d["baths"], "bath") if d.get("baths") else None,
        f"{d['sqft']} sq ft" if d.get("sqft") else None] if x)
    hook = {"kind": "photo", "eyebrow": place.upper() or "ACTIVE LISTING",
            "value": price_full or "This house", "specs": specs, "sub": q}
    auto = d.get("auto") or {}
    units = auto.get("units") or []
    if pt:
        hook["badge"] = (pt.upper() + (f" · {len(units)} UNITS" if len(units) >= 2 else ""))

    if d.get("strRestricted"):
        lbl = {"LTR": "Long-term", "MTR": "Mid-term", "S8": "Section 8", "HH": "House hack", "BRRRR": "BRRRR"}
        legal = [(k, v) for k, v in (d.get("strategies") or {}).items() if k in lbl and num(v) is not None]
        bk = max(legal, key=lambda kv: num(kv[1]), default=None)
        tiles = ([(f"Best · {lbl[bk[0]]}", pretty_money(bk[1]) + "/mo", GREEN if num(bk[1]) > 0 else RED)] if bk else []) + \
                [("Cap rate", d.get("capRate") or "—", INK), ("Cash-on-cash", d.get("coc") or "—", INK)]
        make_scorecard(d.get("address") or "", city_line, price_full, tiles, pill="STR RESTRICTED").save(P("card_scorecard.png"))

    beats = []
    money = lambda x: f"${int(round(float(x))):,}" if x not in (None, "") else None
    # ---- 1. rent, pulled automatically (RentCast) — per unit on multifamily
    if len(units) >= 2:
        total = sum(float(u["rent"]) for u in units)
        rows_u = [{"label": u.get("label") or f"Unit {i + 1}", "value": money(u["rent"]) + "/mo", "color": INK}
                  for i, u in enumerate(units[:6])]
        rows_u.append({"label": "Total rent", "value": money(total) + "/mo", "color": GREEN, "best": True})
        beats.append({"kind": "list", "eyebrow": "RENT BY UNIT · RENTCAST", "headline": f"{money(total)}/mo across {len(units)} units.",
                      "headline_size": 78, "sub": "Live rent estimates for every unit, pulled automatically.",
                      "rows": rows_u, "y_eb": 420, "dur": 4.3,
                      "say": f"Rent: {money(total)}/mo across {len(units)} units (RentCast estimates, pulled automatically)."})
    rent_row = ([] if len(units) >= 2 or not auto.get("ltrRent") else
                [{"label": "Rent", "note": "RentCast estimate", "value": money(auto["ltrRent"]) + "/mo", "color": GREEN}])
    exp_rows = rent_row + [r for r in [
        {"label": "Property tax", "note": (auto.get("taxSrc") or "public records")[:40], "value": money(auto.get("tax")) + "/mo", "color": INK} if auto.get("tax") else None,
        {"label": "Insurance", "note": ("market estimate" if auto.get("insAdjusted") else (auto.get("insSrc") or "regional average"))[:40], "value": money(auto.get("ins")) + "/mo", "color": INK} if auto.get("ins") else None] if r]
    if len(exp_rows) >= 2:
        beats.append({"kind": "list", "eyebrow": "FILLED IN FOR YOU", "headline": "Rent, taxes and insurance. No lookups." if rent_row else "Taxes and insurance. No lookups.",
                      "headline_size": 78, "sub": "Every number sourced, every number editable.",
                      "rows": exp_rows, "y_eb": 440, "dur": 3.9,
                      "say": "Taxes" + (f" {money(auto['tax'])}/mo" if auto.get("tax") else "") + " and insurance"
                             + (f" {money(auto['ins'])}/mo" if auto.get("ins") else "") + " filled in automatically."})
    # ---- 2. rehab estimate from the listing photos
    rh = d.get("rehab") or {}
    if rh.get("range") and "$" in rh["range"]:
        rng = rh["range"].replace("\u2013", "–").replace(" – ", "–").replace("–", " – ")
        scope = []                                   # "Interior: paint…" / "Kitchen refresh, new…" → "interior", "kitchen refresh"
        for x in rh.get("scope") or []:
            w = " ".join(re.split(r"[:,;(—–-]", x)[0].strip().lower().split()[:3])
            if w and w not in scope: scope.append(w)
        scope = scope[:3]
        beats.append({"kind": "stat", "eyebrow": "REHAB ESTIMATE FROM PHOTOS", "headline": rng,
                      "sub": ((rh.get("level") or "").strip() + " rehab" + (": " + ", ".join(scope) if scope else "") + ". Scoped by AI from the listing photos.").strip(),
                      "y_eb": 600, "dur": 4.2,
                      "say": f"AI read the listing photos: {rh.get('level', '').lower() or 'rehab'} at {rng}."})
    if score_s:
        beats.append({"kind": "stat", "eyebrow": "DEAL SCORE", "value": score_s, "unit": "/10",
                      "color": score_color(num(score_s)),
                      "sub": "Your answer, ready in 10 seconds." if AGENT else "Cash flow, price and market in one number.",
                      "card": "scorecard" if d.get("strRestricted") else "hero", "crop": None if d.get("strRestricted") else 0.70,   # app card would say "Best · STR" on a restricted market
                      "say": f"{score_s}/10 deal score.",
                      # bigger property card: tighter header, smaller number, card up to 860x720
                      "y_eb": 376, "value_size": 160, "card_max_h": 710})
    strat_all = d.get("strategies") or {}
    NAMES = [("LTR", "Long-term rental"), ("MTR", "Mid-term rental"), ("STR", "Short-term · Airbnb"),
             ("S8", "Section 8"), ("HH", "House hack"), ("BRRRR", "BRRRR"), ("FLIP", "Fix & flip · profit")]
    str_blocked = bool(d.get("strRestricted"))
    rows = []
    for k, label in NAMES:
        v = strat_all.get(k)
        if not v: continue
        n = num(v.replace("k", "000").replace("K", "000"))
        rows.append({"label": label, "value": pretty_money(v.replace("k", "K")) + ("" if k == "FLIP" else "/mo"),
                     "color": GREEN if (n or 0) > 0 else RED, "_n": n, "_k": k})
        if k == "STR" and str_blocked:     # the app's own flag: local rules restrict Airbnb here
            rows[-1].update({"label": "Airbnb", "tag": "STR RESTRICTED", "color": MUTED, "_blocked": True})
    if cf is not None and len(rows) >= 4:
        monthly = [r for r in rows if r["_k"] != "FLIP" and not r.get("_blocked")]
        best = max(monthly, key=lambda r: r["_n"] if r["_n"] is not None else -1e9) if monthly else None
        if best and (best["_n"] or 0) > 0: best["best"] = True
        npos = sum(1 for r in rows if (r["_n"] or 0) > 0 and not r.get("_blocked"))
        nlegal = sum(1 for r in rows if not r.get("_blocked"))
        head = (f"Cash flows on {npos} of {nlegal} strategies." if npos else "Negative on every strategy.")
        sub = ("Send your client every option in one link." if AGENT else "Every strategy, after mortgage, taxes and insurance.")
        if str_blocked:
            sub = "Airbnb is restricted here — flagged automatically."
        beats.append({"kind": "list", "eyebrow": "CASH FLOW BY STRATEGY", "headline": head, "headline_size": 78,
                      "sub": sub, "rows": rows, "y_eb": 392, "dur": 5.6,
                      "say": (f"{cf_s}/mo as a rental." if cf >= 200 else
                              f"Loses ${abs(int(cf)):,}/mo as a rental." if cf < 0 else f"{cf_s}/mo. Barely.")
                             + (f" Best play: {best['label'].lower()} at {best['value']}." if best and best.get('best') and best['_k'] != 'LTR' else "")
                             + (" Short-term rental? Restricted in this city — DealCaddie flags local STR rules before you buy." if str_blocked else "")})
    elif cf is not None:
        beats.append({"kind": "stat", "eyebrow": "CASH FLOW · LONG-TERM RENTAL", "value": pretty_money(cf_s),
                      "unit": "/mo", "color": GREEN if cf > 0 else RED, "sub": cf_sub, "card": "ltr",
                      "say": (f"{cf_s}/mo as a rental." if cf >= 200 else
                              f"Loses ${abs(int(cf)):,}/mo as a rental." if cf < 0 else f"{cf_s}/mo. Barely.")})

    strat = d.get("strategies") or {}
    names = {"MTR": "mid-term rental", "STR": "Airbnb", "S8": "Section 8", "HH": "house hack", "BRRRR": "BRRRR"}
    alts = [(k, v) for k, v in strat.items() if k not in ("LTR", "FLIP") and (num(v) or 0) > 0]
    best_alt = max(alts, key=lambda kv: num(kv[1]), default=None)
    mo = num(d.get("maxOffer"))
    has_list = cf is not None and len(rows) >= 4          # the list beat already shows the best strategy
    if cf is not None and cf < 0 and best_alt and not has_list:
        nm = names.get(best_alt[0], best_alt[0])
        beats.append({"kind": "stat", "eyebrow": f"AS A {nm.upper()}", "value": pretty_money(best_alt[1]), "unit": "/mo",
                      "color": GREEN, "sub": f"Same {pt or 'house'}. Different strategy.", "card": "strats",
                      "say": f"As a {nm}: {best_alt[1]}/mo."})
    elif mo and asking and mo <= asking * 1.25:            # a max offer far above asking reads as unbelievable — skip it
        diff = abs(asking - mo)
        if mo < asking:
            sub = (f"{short_price(diff)} under asking: your client's opening number." if AGENT
                   else f"{short_price(diff)} under asking to hit your target return.")
            say = f"Max offer: {short_price(mo)}."
        else:
            sub = (f"Room to go {short_price(diff)} over asking and still hit target." if AGENT
                   else f"Still hits the target return {short_price(diff)} over asking.")
            say = f"Worth up to {short_price(mo)}."
        beats.append({"kind": "stat", "eyebrow": "MAX OFFER", "value": short_price(mo), "unit": "",
                      "color": INK, "sub": sub, "card": "maxoffer", "say": say})
    elif d.get("coc"):
        beats.append({"kind": "stat", "eyebrow": "CASH-ON-CASH RETURN", "value": d["coc"], "unit": "",
                      "color": INK, "sub": "What the cash you put in earns each year.", "card": None,
                      "say": f"{d['coc']} cash-on-cash."})

    noun = "listing" if AGENT else (pt or "house")
    if AGENT and pt: noun = f"{pt} listing"
    title = [f"{short_price(price_full) or 'This'} {city} {noun}." if city else f"This {noun}.", q]
    return hook, beats, title


hook, beats, title = pick_copy(data)


timeline = [(render_photo_beat(hook, 3.8), 3.8)]
for b in beats:
    if b.get("kind") == "list":
        timeline.append((render_list_beat(b, b.get("dur", 5.6)), b.get("dur", 5.6)))
    else:
        timeline.append((render_stat_beat(b, 3.8), 3.8))
if AGENT:
    timeline.append((render_end_beat(3.8, extra=f"Agent plans from {AGENT_PRICE}  ·  branded client links"), 3.8))
else:
    timeline.append((render_end_beat(3.6), 3.6))
encode(timeline, out_mp4)
dur = duration

# ------------------------------------------------------------------ cover + caption
Image.open(P("beat1.png")).save(os.path.join(out_dir, "cover.jpg"), quality=92)

city = (data.get("cityLine") or "").split(",")[0].strip()
city_tag = "#" + re.sub(r"[^a-z]", "", city.lower()) + "realestate" if city else "#realestatedeals"
specs = " · ".join(x for x in [
    f"{data['beds']} bed" if data.get("beds") else None,
    f"{data['baths']} bath" if data.get("baths") else None,
    f"{data['sqft']} sqft" if data.get("sqft") else None] if x)
body = " ".join(b["say"] for b in beats)
if AGENT:
    caption = f"""{' '.join(title)}

{specs + '. ' if specs else ''}Your investor client sends you a listing. Paste the link into DealCaddie and reply with real numbers: {body}

Send it as one branded link with your name, photo and brokerage on it. Clients get a private portal to rank deals and request showings, plus comps, financing scenarios side by side and a one-tap Offer Plan.

Agent plans start at {AGENT_PRICE} → dealcaddie.ai

#realestateagent #realtor #investorfriendly #realestateinvesting {city_tag}
"""
else:
    caption = f"""{' '.join(title)}

{specs + '. ' if specs else ''}Pasted the Zillow link into DealCaddie: {body}

Taxes, insurance and rent comps pulled automatically — about 10 seconds start to finish.

Comment a city and I'll run the next one 👇

Try it free · dealcaddie.ai

#realestateinvesting #rentalproperty #cashflow #realestateinvestor {city_tag}
"""
open(os.path.join(out_dir, "caption.txt"), "w").write(caption)
json.dump({"audience": AUDIENCE, "hook": title, "beats": [{k: v for k, v in b.items() if k not in ("color", "rows")} for b in beats],
           "duration": round(dur(out_mp4), 1), "had_photo": os.path.exists(P("photo.jpg")), **data},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
print(f"built {out_mp4} ({dur(out_mp4):.1f}s, photo={'yes' if os.path.exists(P('photo.jpg')) else 'no'}, "
      f"cards={sorted(f for f in os.listdir(work) if f.startswith('card_'))})")

