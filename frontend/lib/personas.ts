export interface Persona {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompts: string[];
}

export const PERSONAS: Persona[] = [
  {
    id: "general",
    label: "General",
    icon: "🔭",
    description: "Your real-time AI industry radar — ask anything about today's digest",
    prompts: [
      "Give me the top 3 highlights from this week's AI digest.",
      "What competitor moves happened this week?",
      "Any new AI model or product releases I should know about?",
      "How does this week's news affect Centific's strategy?",
      "What's the most important AI development this week?",
    ],
  },
  {
    id: "sales_leader",
    label: "Sales Leader",
    icon: "📊",
    description: "Competitive intel & deal intelligence for revenue teams",
    prompts: [
      "What competitor moves happened this week that I should mention in my next customer call?",
      "How does [Company Name]'s latest AI announcement affect our pitch to them?",
      "Give me 3 talking points against Scale AI for a deal I'm closing Friday.",
      "What's the market sentiment on AI data quality right now — any news I can use?",
      "Are there any funding rounds or partnerships announced this week that signal new competition?",
    ],
  },
  {
    id: "account_manager",
    label: "Account Manager",
    icon: "🤝",
    description: "Client health, upsell signals & relationship intelligence",
    prompts: [
      "What AI developments this week are most relevant to my client in [Industry]?",
      "Is there any news about [Company Name] that I should be aware of before my QBR?",
      "Which of my accounts in the [Industry] space might be impacted by this week's AI announcements?",
      "Are there any signals that a competitor is targeting companies like [Company Name]?",
      "What upsell conversations can I start based on this week's AI radar digest?",
    ],
  },
  {
    id: "ai_researcher",
    label: "AI Researcher",
    icon: "🔬",
    description: "Benchmarks, papers, architecture trends & technical depth",
    prompts: [
      "What new model releases or benchmark results were reported this week?",
      "Summarize the key findings of any new research papers in the digest today.",
      "How does [Model Name] compare to the current SOTA on [Benchmark]?",
      "Are there any new open-source models released this week I should evaluate?",
      "What architecture trends are emerging from this week's research papers?",
    ],
  },
  {
    id: "executive_cxo",
    label: "Executive / CXO",
    icon: "🎯",
    description: "Strategic 2-minute brief — market shifts & business implications",
    prompts: [
      "Give me today's top 3 AI signals I need to know before my morning standup.",
      "What's the single biggest competitive threat this week?",
      "Any major moves by OpenAI, Google, or Anthropic that affect our market position?",
      "What should I be watching in AI regulation or policy this week?",
      "Is there anything this week that should change our product or partnership strategy?",
    ],
  },
  {
    id: "customer_success",
    label: "Customer Success",
    icon: "💡",
    description: "Client adoption signals & value conversations for CSMs",
    prompts: [
      "Help me prepare for a check-in call with my client in [Industry] — what AI news is relevant?",
      "What can I share with [Company Name] from this week's digest to add value?",
      "Are there any AI trends this week that could affect my client's roadmap?",
      "What's happening with AI adoption in [Industry] that I should brief my clients on?",
      "Is there anything this week that I should flag as a risk or opportunity for my book of business?",
    ],
  },
  {
    id: "bd_partnerships",
    label: "BD & Partnerships",
    icon: "🤝",
    description: "Ecosystem moves, partnership opportunities & BD signals",
    prompts: [
      "Which companies announced funding this week that might need AI data services?",
      "What new foundation model launches could be potential channel partners for us?",
      "Give me a BD brief on [Company Name] based on their recent news.",
      "Who in the AI ecosystem is expanding that we should be talking to right now?",
      "What ecosystem gaps or whitespace do you see based on this week's digest?",
    ],
  },
];
