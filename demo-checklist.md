Data and infrastructure
- [x] Synthetic glucose data streaming in, covering a normal day, a low, a high, and a sensor dropout

Safety loop (no AI)
- [ ] Rules engine handling urgent low, low, high, and data gap, with simulation tests passing
- [x] Dashboard notification and Twilio SMS delivered to a test phone, with ACK handling working
- [ ] Heartbeat alert demonstrated when the worker or database goes down

Child experience
- [x] Companion chat running on Nemotron 3 Nano with moderation enabled
- [x] Scripted emergency response and parent escalation demonstrated on a test phrase
- [x] Snack logging and one check-in flow working

Parent experience
- [x] Dashboard showing live glucose, day and week charts, snack log, and alert history
- [x] One AI-written daily summary from Nemotron 3 Super, each claim linked to its data

Readiness for the audience
- Default thresholds reviewed by a care-team contact
- Open compliance questions listed (COPPA, HIPAA, device regulation)
- Demo script rehearsed, with a recorded fallback in case of a live failure
