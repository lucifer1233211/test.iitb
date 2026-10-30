import { GoogleGenAI } from "@google/genai";
import { AnomalySignal, Medoid } from "../types";

function getAIClient() {
  const apiKey = import.meta.env.VITE_GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error("Missing VITE_GEMINI_API_KEY");
  }
  return new GoogleGenAI({ apiKey });
}

export async function synthesizeOutcome(signal: AnomalySignal, matches: Medoid[]) {
  try {
    const prompt = `
      System: IIT Bombay Spatio-Temporal Agentic Router
      Signal Detect: ${signal.type} (Score: ${signal.score.toFixed(2)})
      Retrieved Memory Context:
      ${matches.map(m => `- [${m.tier}] ${m.label}: ${m.description}`).join('\n')}
      
      Task: Perform predictive inference. Determine if this signal represents a legitimate security threat based on the retrieved medoids.
      Respond in JSON format:
      {
        "risk_level": "LOW|MEDIUM|HIGH",
        "reasoning": "string",
        "action": "string",
        "prediction": "string"
      }
    `;

    const ai = getAIClient();
    const response = await ai.models.generateContent({
      model: "gemini-1.5-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json"
      }
    });

    return JSON.parse(response.text || '{}');
  } catch (error) {
    console.error("Cortex Error:", error);
    return {
      risk_level: "ERROR",
      reasoning: "Communication failure with Cortex.",
      action: "Standby",
      prediction: "N/A"
    };
  }
}
