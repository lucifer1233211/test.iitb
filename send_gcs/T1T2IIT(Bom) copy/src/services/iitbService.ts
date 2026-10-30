import { GoogleGenAI } from "@google/genai";

function getAIClient() {
  const apiKey = import.meta.env.VITE_GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error("Missing VITE_GEMINI_API_KEY");
  }
  return new GoogleGenAI({ apiKey });
}

export interface IITBDetectionResult {
  anomaly_detected: boolean;
  score: number;
  matched_tier: string;
  action_label: string;
  reasoning: string;
  prediction: string;
  verbose_logs: string[];
  matched_medoid_ids: string[];
}

export async function runIITBInference(mediaBase64: string, location: string, mimeType: string = "image/jpeg"): Promise<IITBDetectionResult> {
  try {
    let mediaData = mediaBase64;
    if (mediaBase64.includes(',')) {
        mediaData = mediaBase64.split(',')[1];
    }

    const prompt = `
        ROLE: IIT Bombay Spatio-Temporal Router
        CONTEXT: Drone feed from ${location}.
        
        REFERENCE DATABASE (DISTILLED):
        - Dataset: Okutama-Action Drone Corpus (Behavioral Baseline)
        - T1: Facility Normals (distilled via FacilityLocation)
        - T2: Behavior Grammar (Okutama Actions, distilled via Log-Determinant)
        - T3: Entity Forensic details (distilled via Mutual Information)

        TASK:
        1. Perform 'STEAD' Reflex: Detect any motion anomaly or behavioral mismatch.
        2. Perform 'Hierarchical RAG' Retrieval: Match the current frame against the distilled Medoid Pool.
        
        Respond in JSON:
        {
          "anomaly_detected": boolean,
          "score": float (0-1),
          "matched_tier": "T1|T2|T3|NONE",
          "action_label": "string",
          "reasoning": "Explain the spatio-temporal mismatch found",
          "prediction": "Final predictive outcome",
          "verbose_logs": [
            "RAG_PROBE: Initializing retrieval against Okutama-Action corpus...",
            "T1_RECON: FacilityLocation search identified 92% match with medoid 'm1'...",
            "T2_RECON: Motion vector analysis suggests [Action Label] behavioral delta...",
            "T3_RECON: Extracting high-entropy forensic details for identity verification...",
            "CORTEX_ROUTE: Final synthesis of retrieved medoids suggests [Anomaly/Normal] state."
          ],
          "matched_medoid_ids": ["m1", "m2", "m3"]
        }
    `;

    const ai = getAIClient();
    const response = await ai.models.generateContent({
      model: "gemini-1.5-flash",
      contents: {
        parts: [
          { text: prompt },
          {
            inlineData: {
              mimeType: mimeType,
              data: mediaData
            }
          }
        ]
      },
      config: {
        responseMimeType: "application/json"
      }
    });

    const text = response.text;
    if (!text) {
      throw new Error("Empty response from IITB Cortex");
    }
    return JSON.parse(text);
  } catch (error) {
    console.error("IITB Inference Error:", error);
    throw error;
  }
}
