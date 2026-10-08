# How to use grokcord

Already installed it? This is the day-to-day guide for **members** (everyone) and **admins** (people with *Manage Server*).
Not installed yet? Start with **[SETUP.md](SETUP.md)**.

---

## For everyone

### 💬 Talk to Grok
Mention the bot anywhere it can read:

```
@grokcord what's the difference between a Layer 1 and a Layer 2?
```

Grok reads the last few messages for context but answers *your* message, in your language. It searches the web and X only when it needs fresh info, and the answer streams in as it's written. Sources show up in small text under the answer.

**Reply to ask about a message.** Hit *Reply* on any message and write:

```
@grokcord is this true?
@grokcord explain this like I'm 5
@grokcord what's in this screenshot?
```

Grok sees the message you replied to, images included.

### ✅ Fact-check any message
Right-click a message (on mobile: long-press) → **Apps → Fact-check with Grok**.

The verdict is posted in the channel so everyone sees it:

| Verdict | Means |
|---|---|
| ✅ TRUE | Checks out |
| 🟢 MOSTLY TRUE | Right, with small errors or missing nuance |
| ⚠️ MISLEADING | Some truth, wrong conclusion or missing context |
| ❌ FALSE | Wrong |
| ❔ UNVERIFIED | No reliable sources either way, or it's an opinion or a joke |

Always click a source or two before you go and correct someone.

### 🧠 Explain · 🌍 Translate
Right-click → **Apps → Explain with Grok** decodes slang, memes, jargon or code.
Right-click → **Apps → Translate with Grok** translates into *your* Discord language (Settings → Language).
Only you see these answers.

### 📜 /tldr: catch up
```
/tldr                      → last 150 messages, only you see it
/tldr messages:400         → read further back
/tldr private:False        → post the summary for everyone
```
You get a one-line TL;DR, who said what, and action items.

### 📡 /pulse: what X is saying
```
/pulse topic:Solana
/pulse topic:GTA 6 trailer hours:Last 6 hours
```
You get the overall mood, the take that's winning, the main viewpoints with @handles, and what's confirmed vs rumour. It's a sample of posts, not a poll.

### ❓ /ask: a clean one-off question
```
/ask question:best budget mic for streaming under $100
/ask question:what's wrong with my code? image:<attach screenshot>
/ask question:write a haiku about Mondays search:False
/ask question:… private:True
```
`search:False` is faster and cheaper when you don't need live info. `private:True` means only you see the answer.

### 🧵 /chat: a thread with memory
```
/chat topic:planning my trip to Japan
```
Opens a thread where Grok answers **every** message (no @ needed) and remembers the whole thread. Great for long back-and-forths without spamming the main channel.

### 🎨 /imagine
```
/imagine prompt:a glossy white orb mascot DJing in a neon club, 3D render
```
Costs more units than text (5 by default).

### 📊 /usage
Shows how many units you have left today. A text answer costs **1 unit**, an image costs **5**. Everything resets at **00:00 UTC**.

---

## For admins

All admin commands live under `/grokcord` and only show for members with **Manage Server**.
To change who can use them: *Server Settings → Integrations → grokcord*.

### 🎭 Personas
```
/grokcord persona style:Analyst scope:This channel only
/grokcord persona style:Roast                       → whole server
/grokcord persona custom:You are the hype-man of a fitness server. Short, energetic, always one actionable tip.
/grokcord persona                                   → show the current one
/grokcord reset-persona scope:This channel only
```

| Persona | Good for |
|---|---|
| **helper** (default) | Any server |
| **analyst** | Trading, crypto, stocks, sports stats |
| **roast** | Memes, off-topic, gaming banter |
| **teacher** | Study groups, beginners, coding help |
| **mod** | Support channels, heated debates |
| **degen** | Crypto communities that want the vibe but honest answers |

A channel persona overrides the server persona.

### 🌍 Language
By default Grok replies in the language each person writes in, and `/tldr` uses the chat's own language.
```
/grokcord language language:Russian      → always Russian
/grokcord language other:Kazakh          → any language not in the list
/grokcord language language:Auto         → back to matching each person
```

### 💸 Spend caps
```
/grokcord limits                         → show current caps
/grokcord limits per_user:20             → each member: 20 units/day
/grokcord limits per_server:300          → whole server: 300 units/day
/grokcord limits per_user:0              → effectively pause grokcord for members
```

Rough guide for a budget: one fact-check, /pulse or @mention answer uses live search and costs a few cents at most. A plain `/ask search:False` is cheaper. Check real numbers in your [xAI console](https://console.x.ai) after a day and tune the caps from there.

### 🎛️ Turn features on or off
```
/grokcord feature feature:/imagine images enabled:False
/grokcord feature feature:@mention chat and replies enabled:False
```
You can switch off: @mention chat, /ask, Fact-check, Explain, Translate, /tldr, /pulse, /imagine, and **web search in chat and /ask** (the cheapest way to cut costs while keeping the bot fully on).

### 🩺 Status
```
/grokcord status
```
Shows the model, the persona in this channel, the caps and anything switched off.

---

## Tips that make it shine
- **Pin a message** in your main channel: *"Right-click any message → Apps → Fact-check with Grok"*. Most people don't know about Apps.
- Give `#trading` the **analyst**, `#memes` **roast** and `#help` the **teacher**.
- Put `/tldr` in your welcome message for people returning to a busy server.
- Use `/chat` for long conversations so main channels stay readable.

## Good to know
- grokcord stores **no message content**, only settings and daily counters.
- It only sends messages to xAI when someone uses it.
- It can't ping @everyone, roles or users.
- It's AI: it can be wrong. That's why fact-checks come with sources.
