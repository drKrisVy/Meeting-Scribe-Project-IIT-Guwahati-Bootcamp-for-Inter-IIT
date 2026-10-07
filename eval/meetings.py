# Scripted test meetings. Each one hides the traps the problem statement cares about.
# "lines" are (speaker, words). "answers" is what a correct record should contain.

MEETINGS = [
    {
        "name": "01_launch_review",
        "voices": ["Samantha", "Daniel", "Karen"],
        "lines": [
            (0, "Okay everyone, let's start the launch review."),
            (1, "Before we start, the Kubernetes cluster was upgraded last night and the Grafana dashboards look healthy."),
            (0, "Good. First topic is the launch date. What if we move the launch to the fifteenth?"),
            (2, "Hmm, I'm not sure. Let me check with marketing first."),
            (1, "We can't ship until the payment bug is fixed anyway."),
            (0, "Right. Also, what if we switch the analytics database to Postgres?"),
            (2, "Let's not do that this quarter. It's too risky."),
            (0, "Fine, no database migration this quarter then."),
            (1, "Back to the launch. Marketing confirmed by email. So, the fifteenth works?"),
            (0, "Yes, okay, we're moving the launch to the fifteenth."),
            (2, "We'll need fifteen, sorry, fifty test devices for the beta."),
            (0, "Priya, can you order the fifty test devices by Friday?"),
            (2, "Yes, I'll do that."),
            (1, "Someone should look into the Grafana alert noise."),
            (0, "Arjun, please update the release notes by end of next week."),
            (0, "That's all, thanks everyone."),
        ],
        "answers": {
            "terms": ["Kubernetes", "Grafana", "Postgres", "Priya", "Arjun"],
            "decisions": [
                ("Move the launch to the fifteenth", "agreed"),
                ("No analytics database migration this quarter", "agreed"),
            ],
            "tasks": [
                # task, owner, deadline, commitment
                ("Order fifty test devices", "Priya", "by Friday", "confirmed"),
                ("Look into the Grafana alert noise", None, None, "suggested"),
                ("Update the release notes", "Arjun", "by end of next week", "assigned"),
            ],
        },
    },
    {
        "name": "02_budget_sync",
        "voices": ["Daniel", "Samantha", "Karen"],
        "lines": [
            (0, "Let's do the quick budget sync."),
            (1, "The cloud bill went up twelve percent last month, mostly from the Redis cache."),
            (0, "That's about two lakh rupees extra."),
            (2, "Should we move to reserved instances? It could save around thirty percent."),
            (0, "Let's decide that next week when finance joins."),
            (1, "I'll take the cost breakdown by service."),
            (0, "Meera, can you get the vendor quotes before the next sync?"),
            (2, "We also need someone to clean up the unused S3 buckets."),
            (0, "And we never approved the extra monitoring spend, so that stays off for now."),
            (1, "Okay, agreed, monitoring spend stays off."),
            (0, "Thanks, see you next week."),
        ],
        "answers": {
            "terms": ["Redis", "S3", "Meera"],
            "decisions": [
                ("Move to reserved instances", "open_question"),
                ("Extra monitoring spend stays off", "agreed"),
            ],
            "tasks": [
                ("Cost breakdown by service", None, None, "confirmed"),
                ("Get the vendor quotes", "Meera", "before the next sync", "assigned"),
                ("Clean up the unused S3 buckets", None, None, "suggested"),
            ],
        },
    },
    {
        "name": "03_incident_retro",
        "voices": ["Karen", "Daniel", "Samantha"],
        "lines": [
            (0, "This is the retro for Tuesday's outage."),
            (1, "The CDN cache expired and every request hit the API directly."),
            (2, "PagerDuty paged the wrong rotation, so nobody was on call for twenty minutes."),
            (0, "And we did not breach the SLA, we were at ninety nine point five percent."),
            (1, "We never rolled back because the deploy wasn't the cause."),
            (0, "Open question: do we keep the CDN provider or not? Let's decide at the next retro."),
            (2, "Rohan, can you fix the PagerDuty rotation today?"),
            (1, "Sure, I'll fix it today."),
            (0, "Someone should add an alert for cache hit ratio."),
            (2, "Let's add a runbook for CDN failures."),
            (0, "Yes, let's do that."),
            (0, "Okay, thanks all."),
        ],
        "answers": {
            "terms": ["CDN", "API", "PagerDuty", "SLA", "Rohan"],
            "decisions": [
                ("Keep the CDN provider", "open_question"),
                ("Add a runbook for CDN failures", "agreed"),
            ],
            "tasks": [
                ("Fix the PagerDuty rotation", "Rohan", "today", "confirmed"),
                ("Add an alert for cache hit ratio", None, None, "suggested"),
            ],
        },
    },
    {
        "name": "04_design_review",
        "voices": ["Samantha", "Karen", "Daniel"],
        "lines": [
            (0, "Welcome to the design review for the onboarding flow."),
            (1, "The new Figma file has three screens instead of five."),
            (2, "I'd like to rebuild the forms in React with TypeScript."),
            (0, "That makes sense, let's do it."),
            (1, "Should we also drop the email verification step?"),
            (2, "Let's not, security needs it."),
            (0, "Agreed, email verification stays."),
            (1, "Ananya, could you share the Figma link with the whole team by tomorrow morning?"),
            (2, "Yep, will do."),
            (0, "What if we add a dark mode later?"),
            (1, "Maybe, no promises."),
            (0, "Great, that's it for today."),
        ],
        "answers": {
            "terms": ["Figma", "React", "TypeScript", "Ananya"],
            "decisions": [
                ("Rebuild the forms in React with TypeScript", "agreed"),
                ("Keep the email verification step", "agreed"),
                ("Add a dark mode later", "proposed"),
            ],
            "tasks": [
                ("Share the Figma link with the team", "Ananya", "by tomorrow morning", "confirmed"),
            ],
        },
    },
]
