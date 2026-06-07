# Virtual Concierge as a Service — Business Plan

## Executive Summary

A white-label AI virtual concierge platform for boutique hotels, built on the Villa Adora Bled proof-of-concept. Hotels get a custom-branded chatbot that handles guest inquiries 24/7, manages bookings, and logs special requests (late check-in/out, etc.) — reducing front-desk workload and improving guest experience.

**Revenue model:** SaaS subscription per hotel, plus one-time setup fee.

---

## The Product

### What it does
- **24/7 guest chat** — answers questions about rooms, policies, breakfast, parking, pets, local attractions
- **Booking flow** — collects guest details, confirms, writes to hotel's database
- **Late check-in/out calendar** — automatically logs guest requests for staff awareness
- **RAG knowledge base** — trained on each hotel's specific data (website, reviews, policies)
- **Admin dashboard** — staff views bookings, calendar events, guest interactions
- **Multi-language** — responds in the guest's language automatically

### Technical stack
- Flask + OpenRouter (LLM-agnostic — works with any model)
- SQLite for bookings and calendar events
- TF-IDF RAG for hotel knowledge (no vector DB needed)
- Deployed on Render (free tier works for small hotels)
- ~$5-10/month hosting cost per hotel

### What makes it different
- **Boutique-focused** — designed for small hotels (5-50 rooms), not enterprise
- **Self-contained** — no external dependencies, no API keys needed beyond OpenRouter
- **Privacy-first** — all data stays on hotel's own server
- **Easy to customize** — hotel data in simple Python/Markdown files
- **Low cost** — runs on free-tier cloud hosting

---

## Target Market

### Ideal customer
- Boutique hotels, B&Bs, guesthouses (5-50 rooms)
- 1-3 front-desk staff (often owner-operated)
- Currently answering the same questions repeatedly via phone/email/WhatsApp
- No budget for enterprise PMS integrations
- Tech-comfortable enough to run a simple web app

### Market size
- **Europe alone:** ~200,000 boutique hotels/B&Bs
- **Global:** ~1.5 million small accommodation providers
- **Serviceable (English-speaking, tech-comfortable):** ~150,000
- **Realistic Year 1 target:** 50-100 hotels

### Competitive landscape
| Solution | Price | Target | Drawback |
|----------|-------|--------|----------|
| HiJiffy | €300-800/mo | Mid-large hotels | Complex, needs PMS integration |
| Asksuite | $200-500/mo | Mid-large hotels | Enterprise-focused |
| Custom chatbot dev | $5,000-20,000 one-time | Any | Expensive, hard to maintain |
| **This solution** | **€99-199/mo** | **Boutique (5-50 rooms)** | **Simple, self-contained** |

---

## Pricing Strategy

### Tier 1 — Starter: €99/month
- Basic chat (hotel info, policies, FAQ)
- Up to 500 conversations/month
- Email support
- Standard knowledge base (website + 10 FAQ items)

### Tier 2 — Professional: €149/month
- Everything in Starter
- Booking flow with confirmation
- Late check-in/out calendar
- Admin dashboard
- Up to 2,000 conversations/month
- Priority support
- Custom knowledge base (unlimited)

### Tier 3 — Premium: €199/month
- Everything in Professional
- Multi-language support (auto-detect)
- WhatsApp/Telegram integration
- Custom branding (hotel logo, colors)
- Unlimited conversations
- Phone support
- Monthly analytics report

### One-time setup fee
- **Starter:** €299
- **Professional:** €499
- **Premium:** €799

---

## Revenue Projections

### Conservative (Year 1)
| Quarter | Hotels | Avg Monthly Revenue | Quarterly Revenue |
|---------|--------|-------------------|-------------------|
| Q1 | 5 | €149 avg | €2,235 |
| Q2 | 15 | €149 avg | €6,705 |
| Q3 | 30 | €159 avg | €14,310 |
| Q4 | 50 | €159 avg | €23,850 |
| **Year 1 Total** | **50** | | **€47,100** |

### Setup fees (Year 1)
- 50 hotels × €499 avg = **€24,950**

### **Total Year 1 Revenue: ~€72,000**

### Optimistic (Year 1)
| Quarter | Hotels | Avg Monthly Revenue | Quarterly Revenue |
|---------|--------|-------------------|-------------------|
| Q1 | 10 | €159 avg | €4,770 |
| Q2 | 30 | €159 avg | €14,310 |
| Q3 | 60 | €169 avg | €30,420 |
| Q4 | 100 | €169 avg | €50,700 |
| **Year 1 Total** | **100** | | **€100,200** |

### Setup fees (Optimistic)
- 100 hotels × €599 avg = **€59,900**

### **Total Year 1 Revenue (Optimistic): ~€160,000**

---

## Year 2-3 Projections

### Year 2 (Conservative)
- 150 hotels (100 existing + 50 new)
- €169 avg monthly × 150 × 12 = **€304,200**
- 50 new setups × €499 = **€24,950**
- **Total: ~€329,000**

### Year 3 (Conservative)
- 350 hotels (150 existing + 200 new)
- €179 avg monthly × 350 × 12 = **€751,800**
- 200 new setups × €499 = **€99,800**
- **Total: ~€851,000**

### Year 3 (Optimistic)
- 500+ hotels
- **Total: ~€1,200,000+**

---

## Cost Structure

### Per-hotel costs
| Item | Cost |
|------|------|
| Render hosting (free tier) | €0-5/mo |
| OpenRouter API (2000 convos) | €3-8/mo |
| Domain + SSL | €1/mo |
| **Total per hotel** | **€4-14/mo** |

### Fixed costs (monthly)
| Item | Cost |
|------|------|
| Your time (10 hrs/week) | €0 (founder) |
| Marketing (Google Ads, content) | €500/mo |
| Legal/accounting | €200/mo |
| Misc (tools, subscriptions) | €100/mo |
| **Total fixed** | **€800/mo** |

### Profitability
- **Break-even:** ~6 hotels (€800 / €149 per hotel)
- **At 50 hotels:** €7,450/mo revenue - €800 fixed - €500 variable = **€6,150/mo profit**
- **At 100 hotels:** €15,900/mo revenue - €800 fixed - €1,000 variable = **€14,100/mo profit**
- **At 350 hotels:** €62,650/mo revenue - €2,000 fixed - €3,500 variable = **€57,150/mo profit**

---

## Go-to-Market Strategy

### Phase 1: Proof of Concept (Months 1-3)
- Villa Adora Bled as live demo
- Document the build process as a repeatable playbook
- Create a "setup package" (config files, knowledge base template, deployment guide)
- Target: 5-10 pilot hotels at discounted rates (€49/mo)

### Phase 2: Early Adopters (Months 4-6)
- Partner with 2-3 boutique hotel associations in Slovenia/Croatia
- Attend 1-2 hospitality trade shows (HITB, Boutique Hotel Conference)
- Content marketing: "How we built an AI concierge for our hotel" blog posts
- Target: 15-30 hotels

### Phase 3: Scale (Months 7-12)
- Hire a part-time sales person (commission-based)
- Partner with hotel website designers (referral commission)
- Add WhatsApp integration (huge demand from hotels)
- Target: 50-100 hotels

### Phase 4: Productize (Year 2)
- Self-service onboarding (hotel fills in a form, bot auto-configures)
- White-label platform (hotels get their own subdomain)
- API for PMS integration (Mews, Cloudbeds)
- Target: 150+ hotels

---

## Key Metrics to Track

| Metric | Target |
|--------|--------|
| Hotels onboarded | 50 by month 12 |
| Monthly churn rate | <5% |
| Average revenue per hotel | >€150/mo |
| Setup time per hotel | <4 hours |
| Guest satisfaction (bot) | >4.0/5.0 |
| Support tickets per hotel | <2/mo |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM quality varies | Use reliable models (Claude, GPT-4), fallback chains |
| Hotels don't trust AI | Position as "assistant to staff", not replacement |
| Competitors enter market | First-mover advantage in boutique segment, build relationships |
| Scaling support load | Self-service docs, video tutorials, community forum |
| Data privacy concerns | All data on hotel's own server, GDPR-compliant by design |

---

## Why This Works

1. **Proven product** — Villa Adora Bled is live and working
2. **Low cost to run** — free-tier hosting, cheap LLM API
3. **High perceived value** — hotels save 5-10 hours/week of staff time
4. **Recurring revenue** — SaaS model with low churn
5. **Scalable** — each hotel is independent, no shared infrastructure
6. **Defensible** — deep integration with hotel operations creates switching costs

---

## Next Steps

1. **Package the product** — create a repeatable setup process (config files, knowledge base template)
2. **Build a landing page** — showcase Villa Adora as demo, explain the value prop
3. **Identify 5 pilot hotels** — offer discounted setup in exchange for testimonials
4. **Create documentation** — setup guide, FAQ, troubleshooting
5. **Set up billing** — Stripe integration for subscription management
6. **Launch** — start with Slovenian/Croatian boutique hotels, expand to EU
