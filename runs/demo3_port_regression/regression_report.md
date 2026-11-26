# Regression report: demo3_port against `demos/port_docs_v2`

**1 real regression(s)**, 3 outdated test(s), 0 to re-check, 1 newly fixed.
Raw old exam: 15/20 before, 13/20 now. On the 17 cases still valid for the new documents: 76%.

## Document changes

- **rotterdam_port_guide**: modified
  - `-Vessels must send the pre-arrival notification at least 24 hours before arrival. Dangerous cargo must be declared at least 48 hours before arrival.`
  - `+Vessels must send the pre-arrival notification at least 48 hours before arrival. Dangerous cargo must be declared at least 72 hours before arrival.`
  - `-Cargo operations at container berths stop when wind speed exceeds 50 km/h. Tug assistance is mandatory when wind speed exceeds 40 km/h.`
  - `-5. Waste and Bunkering`
  - `-Garbage must be landed before departure unless storage capacity is sufficient for the next voyage. Bunkering requires a completed safety checklist signed by th`
  - `+Cargo operations at container berths stop when wind speed exceeds 45 km/h. Tug assistance is mandatory when wind speed exceeds 40 km/h.`

## Broke (facts still present)

- `clz-882f89` (answerable) "According to singapore port guide (2. Pilotage), which number belongs in the blank: "Pilotage is compulsory for vessels of ____ gross tonnage and above.""  
  now: fail; missing or invalid citations  
  agent said: "300"

## Outdated tests (documents changed)

- `mul-e13445` (multi_doc) "What are the requirements for crew shore passes in Rotterdam and Singapore?"  
  now: fail; fact no longer in rotterdam_port_guide, singapore_port_guide: 'Bunkering requires a completed safety checklist'  
  agent said: "In Rotterdam, crew must return on board at least 2 hours before departure. In Singapore, shore passes are required for all crew going ashore and they must retur"
- `clz-1576b6` (answerable) "According to rotterdam port guide (1. Pre-arrival Notice), which number belongs in the blank: "Vessels must send the pre-arrival notification at least ____ hours before arrival.""  
  now: fail; fact no longer in rotterdam_port_guide: '24'  
  agent said: "48"
- `clz-fe6004` (answerable) "According to rotterdam port guide (4. Weather Limits), which number belongs in the blank: "Cargo operations at container berths stop when wind speed exceeds ____ km/h.""  
  now: fail; fact no longer in rotterdam_port_guide: '50'  
  agent said: "45"

## Still failing

- `par-6108d6` (paraphrase) "How many tugboats should I have on board if my ship is really big?"  
  now: fail; LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved  
  agent said: "At least 2 tugs."
- `par-0204c9` (paraphrase) "What should I do with my ship if it starts to blow strongly?"  
  now: fail; LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved  
  agent said: "Stop cargo operations and use tug assistance if wind speed exceeds 40 km/h."
- `ans-977469` (answerable) "What is the minimum wind speed at which tug assistance becomes mandatory?"  
  now: fail; facts missing from answer despite being retrieved  
  agent said: "40 km/h"

Outdated cases should be regenerated with `forge run` on the new documents before trusting a new score.
