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


def pick_copy(d):
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

    beats = []
    if score_s:
        beats.append({"kind": "stat", "eyebrow": "DEAL SCORE", "value": score_s, "unit": "/10",
                      "color": score_color(num(score_s)),
                      "sub": "Your answer, ready in 10 seconds." if AGENT else "Cash flow, price and market in one number.",
                      "card": "hero", "crop": 0.70, "say": f"{score_s}/10 deal score."})
    if cf is not None:
        beats.append({"kind": "stat", "eyebrow": "CASH FLOW · LONG-TERM RENTAL", "value": pretty_money(cf_s),
                      "unit": "/mo", "color": GREEN if cf > 0 else RED, "sub": cf_sub, "card": "ltr",
                      "say": (f"{cf_s}/mo as a rental." if cf >= 200 else
                              f"Loses ${abs(int(cf)):,}/mo as a rental." if cf < 0 else f"{cf_s}/mo. Barely.")})

    strat = d.get("strategies") or {}
    names = {"MTR": "mid-term rental", "STR": "Airbnb", "S8": "Section 8", "HH": "house hack", "BRRRR": "BRRRR"}
    alts = [(k, v) for k, v in strat.items() if k not in ("LTR", "FLIP") and (num(v) or 0) > 0]
    best_alt = max(alts, key=lambda kv: num(kv[1]), default=None)
    mo = num(d.get("maxOffer"))
    if cf is not None and cf < 0 and best_alt:
        nm = names.get(best_alt[0], best_alt[0])
        beats.append({"kind": "stat", "eyebrow": f"AS A {nm.upper()}", "value": pretty_money(best_alt[1]), "unit": "/mo",
                      "color": GREEN, "sub": "Same house. Different strategy.", "card": "strats",
                      "say": f"As a {nm}: {best_alt[1]}/mo."})
    elif mo and asking:
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

    noun = "listing" if AGENT else "house"
    title = [f"{short_price(price_full) or 'This'} {city} {noun}." if city else f"This {noun}.", q]
    return hook, beats, title


hook, beats, title = pick_copy(data)


timeline = [(render_photo_beat(hook, 3.8), 3.8)]
for b in beats:
    timeline.append((render_stat_beat(b, 3.8), 3.8))
if AGENT:
    timeline.append((render_end_beat(3.6, line="Built for agents with investor clients.",
                                     sub=f"Agent plans from {AGENT_PRICE}  ·  branded client links"), 3.6))
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
json.dump({"audience": AUDIENCE, "hook": title, "beats": [{k: v for k, v in b.items() if k != "color"} for b in beats],
           "duration": round(dur(out_mp4), 1), "had_photo": os.path.exists(P("photo.jpg")), **data},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
print(f"built {out_mp4} ({dur(out_mp4):.1f}s, photo={'yes' if os.path.exists(P('photo.jpg')) else 'no'}, "
      f"cards={sorted(f for f in os.listdir(work) if f.startswith('card_'))})")

