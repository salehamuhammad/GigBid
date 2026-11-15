# ADR 0003: Claims carry their evidence ids from the writer onward

The writer returns sentences with evidence ids, not free text. Verification checks each sentence's
skills, numbers, named entities and tenure against the cited items (then all retrieved items), and
removes unsupported sentences before the Critic sees the draft. A number, employer or tenure that
appears in no evidence item is unsupported, whatever a model says. The UI shows each claim's
evidence on hover and keyboard focus.
