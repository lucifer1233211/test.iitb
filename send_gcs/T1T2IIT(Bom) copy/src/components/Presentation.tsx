import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Shield, 
  Cpu, 
  Database, 
  Workflow, 
  ChevronRight, 
  ChevronLeft, 
  Layers, 
  Zap, 
  UserCheck, 
  Search,
  Network,
  Activity
} from 'lucide-react';

const slides = [
  {
    id: 1,
    title: "IIT Bombay Drone Cortex",
    subtitle: "Advanced 3-Tier RAG Pipeline for Autonomous Surveillance",
    icon: <Shield className="w-16 h-16 text-blue-500" />,
    content: "An edge-compute architecture designed for sub-second anomaly detection and behavioral classification in complex urban and industrial environments.",
    points: [
      "Hardware-accelerated feature extraction",
      "Memory-augmented reasoning (RAG)",
      "Tiered forensic analysis"
    ]
  },
  {
    id: 2,
    title: "The Core Flow",
    subtitle: "How signals are processed through the Cortex",
    icon: <Workflow className="w-16 h-16 text-purple-500" />,
    content: "The system follows a sequential multi-stage verification process to ensure zero-latency responses while maintaining high precision.",
    flow: [
      { step: "Signal Ingestion", desc: "Live video stream capture at 30 FPS" },
      { step: "Feature Synthesis", desc: "Edge-node CNN extraction of spatial vectors" },
      { step: "STEAD Scoring", desc: "Intrinsic anomaly validation" },
      { step: "RAG Attribution", desc: "3-Tier memory lookup & matching" }
    ]
  },
  {
    id: 3,
    title: "Tier 1: Spatial Baselines",
    subtitle: "Environmental Normalcy (The 'Where')",
    icon: <Database className="w-16 h-16 text-emerald-500" />,
    content: "Spatial medoids represent the 'normal' state of the environment. If the current frame matches a T1 medoid, the system remains in low-power surveillance mode.",
    points: [
      "Urban Sectors (Standard Flow)",
      "Perimeter Woods (Natural Motion)",
      "Loading Docks (Industrial Baseline)"
    ]
  },
  {
    id: 4,
    title: "Tier 2: Behavioral Patterns",
    subtitle: "Action Profiling (The 'What')",
    icon: <Zap className="w-16 h-16 text-orange-500" />,
    content: "When STEAD scores exceed the threshold, T2 analysis identifies movement patterns such as loitering, prone crawling, or rapid approach.",
    points: [
      "Non-linear loitering detection",
      "Low-profile movement analysis",
      "High-velocity intrusion tracking"
    ]
  },
  {
    id: 5,
    title: "Tier 3: Identity & Memory",
    subtitle: "Forensic Resolution (The 'Who')",
    icon: <UserCheck className="w-16 h-16 text-blue-400" />,
    content: "The final tier matches identity profiles against a recognized pool. This distinguishes authorized personnel from unidentified tactical entities.",
    points: [
      "Authorized Personnel (Alpha Prime)",
      "Autonomous Support Bots",
      "Unauthorized Identity Masking Detection"
    ]
  },
  {
    id: 6,
    title: "The Math of RAG",
    subtitle: "Submodular Optimization & Similarity",
    icon: <Cpu className="w-16 h-16 text-stone-400" />,
    content: "We use Submodular Facility Location functions to prune the stream data down to representative 'medoids'. Similarity is calculated using Cosine Distance.",
    math: [
      { label: "Cosine Similarity", formula: "(A·B) / (||A||*||B||)" },
      { label: "STEAD Score", formula: "Sum(|V_live - V_baseline|)" },
      { label: "Greedy Selection", formula: "f(S ∪ {e}) - f(S)" }
    ]
  },
  {
    id: 7,
    title: "Local Continuity",
    subtitle: "Edge-First Design Philosophy",
    icon: <Network className="w-16 h-16 text-pink-500" />,
    content: "Even without cloud connectivity, the drone maintains a local medoid pool. This 'Local Only' mode ensures mission success in remote or jammed sectors.",
    points: [
      "Persistent session-local database",
      "Dynamic on-the-fly ingestion",
      "Low-latency edge synthesis"
    ]
  },
  {
    id: 8,
    title: "Conclusion",
    subtitle: "Scalable Intelligence",
    icon: <Activity className="w-16 h-16 text-red-500" />,
    content: "The IIT Bombay Drone Cortex represents a leap in autonomous surveillance, combining submodular efficiency with RAG-based identification.",
    points: [
      "99.4% Data Reduction rate",
      "Sub-200ms processing cycles",
      "Adaptive behavioral learning"
    ]
  }
];

export default function Presentation() {
  const [currentSlide, setCurrentSlide] = useState(0);

  const nextSlide = () => setCurrentSlide((prev) => (prev + 1) % slides.length);
  const prevSlide = () => setCurrentSlide((prev) => (prev - 1 + slides.length) % slides.length);

  const slide = slides[currentSlide];

  return (
    <div className="min-h-screen bg-stone-950 text-stone-100 flex flex-col items-center justify-center p-8 font-sans">
      {/* Background Decals */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none opacity-20">
        <div className="absolute top-0 left-0 w-full h-full bg-[radial-gradient(circle_at_50%_50%,#1e1e1e_0%,transparent_100%)]" />
        <div className="absolute -top-24 -left-24 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -right-24 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-5xl">
        {/* Progress Bar */}
        <div className="absolute -top-12 left-0 w-full h-1 bg-stone-800 rounded-full overflow-hidden">
          <motion.div 
            className="h-full bg-blue-500"
            initial={{ width: 0 }}
            animate={{ width: `${((currentSlide + 1) / slides.length) * 100}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={currentSlide}
            initial={{ opacity: 0, x: 20, scale: 0.98 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: -20, scale: 0.98 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
            className="bg-stone-900/50 backdrop-blur-xl border border-stone-800 rounded-2xl p-12 shadow-2xl min-h-[500px] flex flex-col"
          >
            <div className="flex items-start gap-8 mb-8">
              <div className="p-4 bg-stone-800/50 rounded-2xl border border-stone-700 shadow-inner">
                {slide.icon}
              </div>
              <div>
                <motion.h2 
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="text-4xl font-bold tracking-tight mb-2 text-white"
                >
                  {slide.title}
                </motion.h2>
                <motion.p 
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 }}
                  className="text-xl text-stone-400 font-medium"
                >
                  {slide.subtitle}
                </motion.p>
              </div>
            </div>

            <div className="flex-grow grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
              <div>
                <motion.p 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.2 }}
                  className="text-lg text-stone-300 leading-relaxed mb-8"
                >
                  {slide.content}
                </motion.p>

                {slide.points && (
                  <ul className="space-y-4">
                    {slide.points.map((point, i) => (
                      <motion.li 
                        key={i}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.3 + (i * 0.1) }}
                        className="flex items-center gap-3 text-stone-400"
                      >
                        <div className="w-1.5 h-1.5 bg-blue-500 rounded-full" />
                        {point}
                      </motion.li>
                    ))}
                  </ul>
                )}

                {slide.math && (
                  <div className="space-y-4">
                    {slide.math.map((m, i) => (
                      <motion.div 
                        key={i}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.3 + (i * 0.1) }}
                        className="bg-black/30 p-4 rounded-xl border border-stone-800"
                      >
                        <div className="text-xs text-stone-500 font-mono mb-1">{m.label}</div>
                        <div className="text-lg font-serif text-blue-400 italic tracking-widest">{m.formula}</div>
                      </motion.div>
                    ))}
                  </div>
                )}
              </div>

              <div className="hidden md:flex justify-center">
                {slide.flow ? (
                  <div className="flex flex-col gap-4 w-full">
                    {slide.flow.map((f, i) => (
                      <motion.div 
                        key={i}
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ delay: 0.4 + (i * 0.1) }}
                        className="bg-stone-800/80 p-4 rounded-xl border-l-4 border-purple-500 relative"
                      >
                        <div className="font-bold text-stone-100">{f.step}</div>
                        <div className="text-sm text-stone-400">{f.desc}</div>
                        {i < slide.flow.length - 1 && (
                          <div className="absolute -bottom-4 left-4 text-purple-500">
                            <ChevronRight className="rotate-90 w-4 h-4" />
                          </div>
                        )}
                      </motion.div>
                    ))}
                  </div>
                ) : (
                  <div className="w-full aspect-square bg-gradient-to-br from-stone-800/50 to-stone-900/50 rounded-full border border-stone-800 flex items-center justify-center p-12 opacity-50 relative overflow-hidden">
                    <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(59,130,246,0.1),transparent_70%)]" />
                    <Layers className="w-32 h-32 text-stone-700" />
                  </div>
                )}
              </div>
            </div>

            <div className="mt-12 flex justify-between items-center text-stone-500 text-sm font-mono">
              <div>SLIDE {currentSlide + 1} / {slides.length}</div>
              <div className="flex gap-4">
                <button 
                  onClick={prevSlide}
                  className="p-3 bg-stone-800 hover:bg-stone-700 rounded-full transition-colors border border-stone-700"
                >
                  <ChevronLeft className="w-6 h-6" />
                </button>
                <button 
                  onClick={nextSlide}
                  className="p-3 bg-blue-600 hover:bg-blue-500 text-white rounded-full transition-colors shadow-lg shadow-blue-500/20"
                >
                  <ChevronRight className="w-6 h-6" />
                </button>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="mt-12 text-stone-600 text-xs uppercase tracking-[0.3em] font-bold">
        IIT Bombay Drone Research & Development • Internal Use Only
      </div>
    </div>
  );
}
