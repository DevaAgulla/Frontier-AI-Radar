export interface Persona {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompts: string[];
}

export const PERSONAS: Persona[] = [
  {
    id: "researcher",
    label: "AI Researcher",
    icon: "🔬",
    description: "Deep technical analysis & paper insights",
    prompts: [
      "What are the benchmark improvements in today's model releases?",
      "Which papers have the most novel methodology?",
      "Summarize the technical contributions of [paper name]",
      "How do today's findings compare to last week's research trends?",
    ],
  },
  {
    id: "sales_leader",
    label: "Sales Leader",
    icon: "📊",
    description: "Competitive intel & market positioning",
    prompts: [
      "What competitor moves should I know before my call today?",
      "How does [our product] compare to what was announced?",
      "Top 3 talking points for a pitch to [company name]?",
      "What pricing changes happened that affect our positioning?",
    ],
  },
  {
    id: "executive",
    label: "Executive",
    icon: "🎯",
    description: "High-level strategic signals",
    prompts: [
      "What are the 3 most strategically important developments today?",
      "Which funding rounds should we be aware of?",
      "What does today's digest mean for our roadmap?",
      "Summarize all competitor activity in 2 sentences.",
    ],
  },
];
