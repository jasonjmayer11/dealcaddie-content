#!/usr/bin/env python3
"""Feature Showcase reels: real app screens on phones, 5 features carousel-style, pricing end card.

Usage: python3 scripts/assemble_showcase.py <template|auto> <out.mp4>
No app run needed — screens come from assets/showcase/ (the same shots used on dealcaddie.ai).
Templates rotate (auto) so each showcase post highlights a different set of features.
Writes <out>, cover.jpg, caption.txt, meta.json next to it.
"""
import datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reelkit import *          # noqa: F401,F403
import reelkit as rk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = lambda n: os.path.join(ROOT, "assets", "showcase", f"{n}.png")
INVESTOR_PRICE = os.environ.get("INVESTOR_PRICE") or "$9.99/mo"
AGENT_PRICE = os.environ.get("AGENT_PRICE") or "$39.99/mo"

def F(img, eyebrow, headline, sub, wide=False):
    return {"image": S(img), "eyebrow": eyebrow, "headline": headline, "sub": sub, "wide": wide}

TEMPLATES = {
    "investor-core": {
        "audience": "investor",
        "intro": ("Paste a Zillow link. Get the whole analysis.", "5 things DealCaddie does in seconds", ["pipeline", "analysis", "maxoffer"]),
        "features": [
            F("analysis", "THE VERDICT", "Deal score + Buy, Watch or Pass", "Taxes, insurance and rent fill in for you."),
            F("pipeline", "PIPELINE", "Every deal in one list", "Score, cash flow and status on every card."),
            F("projections", "LONG-TERM NUMBERS", "See year 30 before you buy", "Equity, cash flow and net proceeds vs. an index fund."),
            F("maxoffer", "MAX OFFER", "Know your number before you offer", "Set your target return. Get the most you can pay."),
            F("compare", "COMPARE", "Put deals side by side", "Best value marked in every row. Ask Caddie which one."),
        ],
        "hook": "5 things DealCaddie does in seconds.",
    },
    "agent-core": {
        "audience": "agent",
        "intro": ("Built for agents with investor clients.", "Your whole investor workflow in one app", ["portal_new", "deals", "lead"]),
        "features": [
            F("deals_minneapolis", "DEALS MAP", "Search a market by cash flow", "Set a client's buy box. Every pin is already underwritten.", wide=True),
            F("portal_new", "CLIENT PORTAL", "A private portal for every client", "They rank deals, react and request showings."),
            F("lead", "BRANDED LINKS", "Every share is a lead", "Your name, headshot, brokerage and logo on every link."),
            F("offerplan", "OFFER PLAN", "An offer plan in one tap", "Opening, target and walk-away, plus what the seller nets.", wide=True),
            F("scenarios", "FINANCING SCENARIOS", "Show them the seller credit", "Side-by-side financing your client can edit."),
        ],
        "hook": "Agents: your investor clients will love this.",
    },
    "investor-edge": {
        "audience": "investor",
        "intro": ("Your spreadsheet can't do this.", "5 more reasons investors switch", ["aitake", "analysis", "comps"]),
        "features": [
            F("aitake", "CADDIE'S TAKE", "A second opinion on every deal", "The call in plain English, plus red flags to ask about."),
            F("comps", "COMPARABLE SALES", "Recent sales + a suggested offer", "Asking vs. comp average, $/sq ft, days on market."),
            F("scenarios", "FINANCING SCENARIOS", "Compare offers side by side", "Down payment, rate, seller credit: cash to close and monthly."),
            F("strategies", "7 STRATEGIES", "Every strategy, side by side", "Long-term, mid-term, Airbnb, Section 8, house hack, BRRRR, flip."),
            F("share", "SHARE", "Send the whole deal in one link", "Your partner opens it on their phone. No login."),
        ],
        "hook": "Your spreadsheet can't do this.",
    },
    "agent-workflow": {
        "audience": "agent",
        "intro": ("From listing to showing in one link.", "How agents run investor clients on DealCaddie", ["rank", "buybox", "contact"]),
        "features": [
            F("buybox", "BUY BOX ALERTS", "Deals find your clients", "New matches come to you first. Send the good ones."),
            F("rank", "RANKED SHORTLIST", "Clients rank their favorites", "Their order syncs back to your Clients tab."),
            F("contact", "SHOWING REQUESTS", "Know who to show first", "Clients request a showing right from the deal."),
            F("share", "CUSTOM SHARE LINKS", "Choose exactly what they see", "Strategies, scenarios and Caddie's verdict, toggled per link."),
            F("packet", "PDF PACKETS", "The packet that closes the meeting", "A ranked shortlist with your name on every page.", wide=True),
        ],
        "hook": "From listing to showing in one link.",
    },
}
ORDER = ["investor-core", "agent-core", "investor-edge", "agent-workflow"]

def pick(name):
    if name in TEMPLATES:
        return name
    # auto: three showcase slots a week, rotating through the templates
    d = datetime.datetime.utcnow().date()
    slot = (d - datetime.date(2026, 1, 1)).days // 2
    return ORDER[slot % len(ORDER)]

name, out_mp4 = pick(sys.argv[1]), sys.argv[2]
T = TEMPLATES[name]
out_dir = os.path.dirname(os.path.abspath(out_mp4))
work = os.path.join(out_dir, "work_showcase"); os.makedirs(work, exist_ok=True)
rk.init(work)

agent = T["audience"] == "agent"
price_line = f"Agent plans from {AGENT_PRICE}" if agent else f"Investor plans from {INVESTOR_PRICE}"
title, sub, hero = T["intro"]
os.environ.setdefault("MUSIC_VARIANT", "2")
hero_img = [S(h) for h in hero] if isinstance(hero, list) else S(hero)
timeline = [(render_showcase_intro(title, sub, hero_img, 3.0), 3.0)]
feats = T["features"]
for i, f in enumerate(feats, 1):
    timeline.append((render_showcase_beat(f, 3.6, i, len(feats)), 3.6))
timeline.append((render_end_beat(3.6, line=price_line,
                                 sub="14-day free trial  ·  iPhone, Android and web"), 3.6))
track = encode(timeline, out_mp4, still_at=1.6)
Image.open(P("beat1.png")).convert("RGB").save(os.path.join(out_dir, "cover.jpg"), quality=92)

bullets = "\n".join(f"{['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣'][i]} {f['headline']}: {f['sub']}" for i, f in enumerate(feats))
if agent:
    tags = "#realestateagent #realtor #investorfriendly #realestateinvesting #realtortips"
    cta = f"Agent plans start at {AGENT_PRICE}. 14-day free trial → dealcaddie.ai"
else:
    tags = "#realestateinvesting #rentalproperty #cashflow #realestateinvestor #househacking"
    cta = f"Investor plans start at {INVESTOR_PRICE}. Free to try → dealcaddie.ai"
caption = f"""{T['hook']}

{bullets}

{cta}

#dealcaddie {tags}
"""
open(os.path.join(out_dir, "caption.txt"), "w").write(caption)
json.dump({"template": name, "audience": T["audience"], "hook": [T["hook"]], "soundtrack": track,
           "duration": round(duration(out_mp4), 1), "had_photo": True, "price": price_line,
           "score": "n/a", "ltrCashflow": "n/a"},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
print(f"built {out_mp4} ({duration(out_mp4):.1f}s, template={name}, music={track})")
