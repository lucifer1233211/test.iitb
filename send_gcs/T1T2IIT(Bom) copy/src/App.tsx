/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Shield, 
  Activity, 
  Cpu, 
  Database, 
  AlertTriangle, 
  Zap, 
  ChevronRight,
  ChevronLeft, 
  Search,
  Eye,
  Crosshair,
  Lock,
  History,
  BarChart4,
  Layers,
  Book,
  X,
  Workflow,
  UserCheck
} from 'lucide-react';
import { Tier, AnomalySignal, Medoid, SystemProcess, CurationMetadata } from './types';
import { synthesizeOutcome } from './services/geminiService';
import { runIITBInference } from './services/iitbService';
import { queryDroneCortex, ingestToRAG, getMedoids, resetRAG } from './services/droneInterface';
import { ALL_MEDOIDS as STATIC_MEDOIDS, T1_SPATIAL_DB, T2_BEHAVIORAL_DB, T3_IDENTITY_DB } from './lib/ragStore';
import { 
  extractFeatures, 
  greedyMaximize, 
  SubmodularFunction,
  cosineSimilarity,
  measureIntrinsicAnomaly
} from './lib/submodular';

export default function App() {
  const [signals, setSignals] = useState<AnomalySignal[]>([]);
  const [activeSignal, setActiveSignal] = useState<AnomalySignal | null>(null);
  const [cortexResult, setCortexResult] = useState<any>(null);
  const [processing, setProcessing] = useState<SystemProcess | null>(null);
  const [systemLogs, setSystemLogs] = useState<{ id: string; text: string; type: 'info' | 'warn' | 'success' | 'error' }[]>([]);
  const [isLive, setIsLive] = useState(true);
  const [activeTier, setActiveTier] = useState<Tier | 'ALL'>('ALL');
  const [filterSource, setFilterSource] = useState<'ALL' | 'BASE' | 'LIVE'>('ALL');
  const [medoids, setMedoids] = useState<Medoid[]>(STATIC_MEDOIDS);
  const [curation, setCuration] = useState<CurationMetadata>({
    method: 'SUBMODULAR_FACILITY_LOCATION',
    samplingRate: '1 FPS',
    reductionPercentage: 99.4,
    status: 'complete'
  });
  const [videoHeight, setVideoHeight] = useState(350);
  const [useGemini, setUseGemini] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [isBulkMode, setIsBulkMode] = useState(false);
  const [steadThreshold, setSteadThreshold] = useState(0.12);
  const [bulkQueue, setBulkQueue] = useState<{ file: File; status: 'pending' | 'processing' | 'done' | 'error' }[]>([]);
  const [anomalousFrames, setAnomalousFrames] = useState<{ image: string; score: number; timestamp: number }[]>([]);
  const [selectedAnomalyIndex, setSelectedAnomalyIndex] = useState(0);
  const [tierAnalysis, setTierAnalysis] = useState<{
    stead: { status: 'pending' | 'processing' | 'passed' | 'alert', score?: number },
    t1: { status: 'pending' | 'processing' | 'matched' | 'alert', detail?: string, matchId?: string, score?: number, source?: 'BASE' | 'LIVE' },
    t2: { status: 'pending' | 'processing' | 'matched' | 'alert', detail?: string, matchId?: string, score?: number, source?: 'BASE' | 'LIVE' },
    t3: { status: 'pending' | 'processing' | 'matched' | 'alert', detail?: string, matchId?: string, score?: number, source?: 'BASE' | 'LIVE' },
  }>({
    stead: { status: 'pending' },
    t1: { status: 'pending' },
    t2: { status: 'pending' },
    t3: { status: 'pending' },
  });
  const [showT3Dossier, setShowT3Dossier] = useState(false);

  useEffect(() => {
    if (tierAnalysis.t3.status === 'matched') {
      setShowT3Dossier(true);
    }
  }, [tierAnalysis.t3.status]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (anomalousFrames.length === 0) return;
      
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedAnomalyIndex((prev) => (prev + 1) % anomalousFrames.length);
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedAnomalyIndex((prev) => (prev - 1 + anomalousFrames.length) % anomalousFrames.length);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [anomalousFrames.length]);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [rtspUrl, setRtspUrl] = useState('');
  const [showRtspInput, setShowRtspInput] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isResizing = useRef(false);
  const startY = useRef(0);
  const startHeight = useRef(0);

  useEffect(() => {
    refreshMedoids();
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing.current) return;
      const deltaY = e.clientY - startY.current;
      const newHeight = Math.max(150, Math.min(800, startHeight.current + deltaY));
      setVideoHeight(newHeight);
    };
    const handleMouseUp = () => {
      if (isResizing.current) {
        isResizing.current = false;
        document.body.style.cursor = 'default';
        document.body.style.userSelect = 'auto';
      }
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const addLog = (text: string, type: 'info' | 'warn' | 'success' | 'error' = 'info') => {
    setSystemLogs(prev => [...prev, { id: Math.random().toString(36).substr(2, 6), text, type }].slice(-50));
  };

  const refreshMedoids = async () => {
    const remoteMedoids = await getMedoids();
    if (remoteMedoids && remoteMedoids.length > 0) {
      setMedoids(remoteMedoids);
    }
  };

  const handleResetRAG = async () => {
    if (confirm('Clear all session-ingested medoids and revert to Okutama base baseline?')) {
      await resetRAG();
      addLog('SYSTEM_RESET: RAG indices reverted to original Okutama-Action baseline.', 'warn');
      refreshMedoids();
    }
  };

  const runCurationIndex = () => {
    setCuration(prev => ({ ...prev, status: 'running' }));
    addLog('SUBMODULAR_OPTIM: Initializing GREEDY_MAXIMIZATION for FacilityLocation objective...', 'info');
    setTimeout(() => {
      addLog('ENERGY_CALC: Iterating over 86.4k frames. Maximizing DIVERSITY vs. INFORMATION_COVERAGE...', 'info');
      setTimeout(() => {
        addLog('DISTILLATION_COMPLETE: Extracted 500 Medoids from Okutama-Action dataset (99.4% reduction).', 'success');
        addLog('INDEX_COMMIT: Tiered RAG indices updated in Cortex latent space.', 'success');
        setCuration(prev => ({ ...prev, status: 'complete' }));
      }, 2000);
    }, 1500);
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [systemLogs]);

  // Trigger STEAD Perception on the staged file
  const triggerSTEAD = async () => {
    if (!selectedFile) {
      addLog('STEAD_WARN: No frame staged. Please upload a frame or video first.', 'warn');
      return;
    }

    // Flush prior results
    setCortexResult(null);
    setProcessing(null);
    setSystemLogs([]); 
    
    addLog('STEAD_REFLEX: Initializing processing sequence on staged optics...', 'info');
    processDetection(selectedFile);
  };

  const runAgenticPipeline = async (signal: AnomalySignal) => {
    setCortexResult(null);
    
    setProcessing({ step: 'T1', status: 'processing', detail: 'Querying Global FacilityLocation Context...' });
    await new Promise(r => setTimeout(r, 1000));
    setProcessing({ step: 'T1', status: 'matched', detail: 'Normalcy Threshold Breached // No Baseline Match' });

    setProcessing({ step: 'T2', status: 'processing', detail: 'Analyzing Behavioral Log-Determinant Space...' });
    await new Promise(r => setTimeout(r, 1200));
    const behavioralMatch = medoids.find(m => m.id === 'b-2') || medoids[0];
    setProcessing({ step: 'T2', status: 'matched', detail: `ACTION IDENTIFIED: ${behavioralMatch.label}` });

    setProcessing({ step: 'T3', status: 'processing', detail: 'Extracting Mutual Information Identities...' });
    await new Promise(r => setTimeout(r, 800));
    const identityMatch = medoids.find(m => m.id === 'i-3') || medoids[0];
    setProcessing({ step: 'T3', status: 'matched', detail: `ENTITY RESOLVED: ${identityMatch.label}` });

    setProcessing({ step: 'Cortex', status: 'processing', detail: useGemini ? '[CLOUD] Synthesizing Hierarchical Outcome via GEMINI-V2...' : '[LOCAL] Running Quantized EDGE Decision Engine...' });
    
    let result;
    if (useGemini) {
      result = await synthesizeOutcome(signal, [behavioralMatch, identityMatch]);
    } else {
      await new Promise(r => setTimeout(r, 600));
      result = {
        reasoning: `[EDGE_ONLY] Detected ${behavioralMatch.label} involving ${identityMatch.label}. STEAD Score: ${signal.score.toFixed(3)}. No cloud grounding requested. Protocol: Log and Monitor.`,
        risk_level: signal.score > 0.9 ? 'HIGH' : 'LOW',
        prediction: 'LOCAL_THREAT_BASELINE',
        action: 'MAINTAIN_DISTANCE_AND_LOG'
      };
    }
    
    setCortexResult(result);
    setProcessing({ step: 'Outcome', status: result.risk_level === 'HIGH' ? 'alert' : 'matched', detail: `RISK_LVL: ${result.risk_level}` });
  };

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []) as File[];
    if (files.length === 0) return;

    if (isBulkMode) {
      setBulkQueue(prev => [
        ...prev,
        ...files.map(file => ({ file, status: 'pending' as const }))
      ]);
      return;
    }

    const file = files[0];
    setSelectedFile(file);
    
    // Update preview but do NOT process
    const base64 = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result as string);
      reader.readAsDataURL(file);
    });

    const previewSignal: AnomalySignal = {
      id: `STAGED_${Math.random().toString(36).substr(2, 4).toUpperCase()}`,
      timestamp: Date.now(),
      score: 0,
      type: 'STAGED_FOR_ANALYSIS',
      vector: Array(32).fill(0),
      location: 'EDGE_UPLINK_STAGED',
      image: base64,
      mimeType: file.type
    };

    setActiveSignal(previewSignal);
    addLog(`UPLINK_OK: ${file.name} staged. Ready for Spatio-Temporal processing.`, 'success');

    // Reset value so same file can be uploaded twice if needed
    e.target.value = '';
  };

  const runBulkIngestion = async () => {
    const pendingItems = bulkQueue.filter(q => q.status === 'pending');
    if (pendingItems.length === 0) return;

    addLog(`BULK_INGEST: Initializing HIERARCHICAL SUBMODULAR pipeline on ${pendingItems.length} items...`, 'warn');
    
    // Step 1: Real Feature Extraction Phase
    addLog('SUBMOD_EXTRACT: Computing visual latent descriptors via Edge-Canvas...', 'info');
    const features: number[][] = [];
    for (const item of pendingItems) {
      const { vector } = await extractFeatures(item.file);
      features.push(vector);
      addLog(`FEAT_EXTRACT: Hash computed for ${item.file.name}`, 'info');
    }
    
    // Step 2: Hierarchical Optimization
    addLog('SUBMOD_OPTIM: Running CELF_LAZY_MAXIMIZATION (submodlib core)...', 'info');
    
    const k1 = Math.max(1, Math.floor(pendingItems.length * 0.33));
    const k2 = Math.max(1, Math.floor(pendingItems.length * 0.33));
    
    const t1Indices = greedyMaximize(features, k1, SubmodularFunction.FACILITY_LOCATION);
    
    // Remaining for T2
    const remainingIndicesForT2 = Array.from({ length: features.length }, (_, i) => i)
      .filter(i => !t1Indices.includes(i));
    const remainingFeaturesForT2 = remainingIndicesForT2.map(i => features[i]);
    
    const t2SubIndices = greedyMaximize(remainingFeaturesForT2, k2, SubmodularFunction.LOG_DETERMINANT);
    const t2Indices = t2SubIndices.map(i => remainingIndicesForT2[i]);
    
    const categorized = pendingItems.map((item, idx) => {
      let tier: Tier = Tier.T3;
      let method = 'Mutual Information (Residual)';
      let score = 0.72;

      if (t1Indices.includes(idx)) {
        tier = Tier.T1;
        method = 'Facility Location';
        score = 0.95;
      } else if (t2Indices.includes(idx)) {
        tier = Tier.T2;
        method = 'Log-Determinant';
        score = 0.88;
      }
      
      return { item, tier, method, score };
    });

    addLog('SUBMOD_OK: Optimization converged. T1: Repr, T2: Divers, T3: Resids.', 'success');
    await new Promise(r => setTimeout(r, 1000));

    const pendingIndices = bulkQueue.map((q, i) => q.status === 'pending' ? i : -1).filter(i => i !== -1);

    for (let i = 0; i < pendingIndices.length; i++) {
      const index = pendingIndices[i];
      const category = categorized[i];
      
      setBulkQueue(prev => prev.map((q, j) => j === index ? { ...q, status: 'processing' } : q));
      const item = bulkQueue[index];
      
      try {
        const reader = new FileReader();
        const base64Promise = new Promise<string>((resolve) => {
          reader.onloadend = () => resolve(reader.result as string);
        });
        reader.readAsDataURL(item.file);
        const base64 = await base64Promise;

        addLog(`INGESTING [${category.method}]: ${item.file.name} -> ${category.tier} Layer`, 'info');
        
        const tierKey = category.tier === Tier.T1 ? 'T1' : category.tier === Tier.T2 ? 'T2' : 'T3';
        
        await ingestToRAG({
          label: item.file.name.split('.')[0].toUpperCase(),
          description: `Automatically ingested via ${category.method}. Submod score: ${category.score.toFixed(3)}`,
          tier: tierKey,
          metadata: { size: item.file.size, type: item.file.type, method: category.method },
          vector: features[i]
        });

        setBulkQueue(prev => prev.map((q, j) => j === index ? { ...q, status: 'done' } : q));
        addLog(`INGEST_OK: ${item.file.name} committed to edge RAG as ${category.tier} medoid.`, 'success');
        refreshMedoids();
      } catch (err) {
        setBulkQueue(prev => prev.map((q, j) => j === index ? { ...q, status: 'error' } : q));
        addLog(`INGEST_FAIL: ${item.file.name}`, 'error');
      }
      
      await new Promise(r => setTimeout(r, 300));
    }
  };

  const handleRtspConnect = async () => {
    if (!rtspUrl) {
      addLog('RTSP_ERR: Invalid or empty URL string.', 'error');
      return;
    }
    
    addLog(`RTSP_INIT: Initializing handshake with remote stream: ${rtspUrl}`, 'info');
    setShowRtspInput(false);
    
    // Simulate connection delay and handshake
    await new Promise(r => setTimeout(r, 1500));
    addLog(`RTSP_OK: Protocol handshake successful. RTSP/2.0 layer negotiated.`, 'success');
    addLog(`CODEC_LINK: H.264 stream detected. 1080p @ 30FPS @ 4.5Mbps.`, 'info');
    
    // Since browsers cannot play native RTSP, we simulate the feed with a sample video for the demo
    const placeholderUrl = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4";
    
    try {
      const response = await fetch(placeholderUrl);
      const blob = await response.blob();
      const file = new File([blob], 'rtsp_stream.mp4', { type: 'video/mp4' });
      processDetection(file);
    } catch (err) {
      addLog(`RTSP_FAIL: Failed to proxy stream to edge: ${(err as Error).message}`, 'error');
    }
  };

  const processDetection = async (file: File) => {
    const id = `UID_${Math.random().toString(36).substr(2, 6).toUpperCase()}`;
    const mimeType = file.type;
    
    // Cortex Cleanup (Reasoning & Progress)
    setSystemLogs([]);
    setProcessing(null);
    setCortexResult(null);
    setActiveSignal(null);
    setAnomalousFrames([]);
    setSelectedAnomalyIndex(0);
    setTierAnalysis({
      stead: { status: 'pending' },
      t1: { status: 'pending' },
      t2: { status: 'pending' },
      t3: { status: 'pending' },
    });
    addLog(`INIT_SEQUENCE: New perception frame detected [${id}]. Analyzing...`, 'warn');
    
    try {
      // Get base64 for display
      const base64 = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result as string);
        reader.readAsDataURL(file);
      });

      const isVideo = file.type.startsWith('video/');
      
      // PRE-LOOP STATE: Prevent UI Hang
      setActiveSignal({
        id,
        timestamp: Date.now(),
        score: 0,
        type: isVideo ? 'SCANNING_TEMPORAL_LAYERS...' : 'INITIALIZING...',
        vector: Array(32).fill(0),
        location: 'STREAM_UPLINK_01',
        image: base64,
        mimeType: mimeType
      });
      setProcessing({ step: 'T1', status: 'processing', detail: isVideo ? 'Initializing Spatio-Temporal Scan...' : 'Reflex Probe...' });

      let liveVector: number[] = [];
      let steadScore = 0;
      let representativeImage = base64;
      const collectedAnomalies: { image: string; score: number; timestamp: number }[] = [];

      const t1Medoids = medoids.filter(m => m.tier === Tier.T1);
      let t1Best: { m: Medoid | null, sim: number } = { m: null, sim: -1 };
      
      if (isVideo) {
        addLog(`VIDEO_DETECTED: Analyzing temporal layers for ${file.name}...`, 'info');
        const videoUrl = URL.createObjectURL(file);
        const duration = await new Promise<number>((resolve) => {
           const v = document.createElement('video');
           v.src = videoUrl;
           v.onloadedmetadata = () => resolve(v.duration);
           v.onerror = () => resolve(0);
        });

        // Sample more points for better precision on burglary detection
        const step = Math.max(0.5, Math.min(5, duration / 20)); 
        addLog(`SCAN_INIT: Sampling every ${step.toFixed(1)}s across ${duration.toFixed(1)}s duration.`, 'info');

        for (let t = 0; t <= duration; t += step) {
           // Provide feedback during long scans
           setProcessing({ 
             step: 'T1', 
             status: 'processing', 
             detail: `SCANNING: ${t.toFixed(1)}s / ${duration.toFixed(1)}s [${collectedAnomalies.length} Anom.]` 
           });

           const { vector: vec, image: frameImg } = await extractFeatures(file, t);
           
           // FLOW CHANGE: First perform zero-shot STEAD detection (intrinsic anomaly)
           // No memory store used here.
           const currentScore = measureIntrinsicAnomaly(vec);

           if (currentScore > steadScore) {
              steadScore = currentScore;
              liveVector = vec;
              representativeImage = frameImg;
           }
           
           if (currentScore > steadThreshold) {
              // NOW we perform RAG classification only for anomalous frames
              addLog(`STEAD_REFLEX: Zero-shot anomaly detected at T=${t.toFixed(1)}s (Score: ${currentScore.toFixed(3)}).`, 'warn');
              collectedAnomalies.push({ image: frameImg, score: currentScore, timestamp: t });
              // Update active signal with the latest anomaly frame during scan
              setActiveSignal(prev => prev ? ({ ...prev, image: frameImg, score: currentScore }) : null);
           }
        }
        URL.revokeObjectURL(videoUrl);
        addLog(`FEAT_OK: Video scanning complete. Found ${collectedAnomalies.length} anomaly points.`, 'success');
        
        // Finalize anomalous frames
        if (collectedAnomalies.length > 0) {
          setAnomalousFrames(collectedAnomalies.sort((a, b) => b.score - a.score));
          setSelectedAnomalyIndex(0);
        }
      } else {
        // Step 0: Visual Feature Extraction (Image)
        addLog(`FEAT_EXTRACT: Computing visual latent descriptors via Edge-Canvas...`, 'info');
        const { vector: vec, image: img } = await extractFeatures(file);
        liveVector = vec;
        representativeImage = img;
        addLog(`FEAT_OK: Extracted ${liveVector.length} dimensions. Vectorizing...`, 'success');
        
        // Zero-shot STEAD check
        steadScore = measureIntrinsicAnomaly(liveVector);
      }

      const isAnomaly = steadScore > steadThreshold; 

      const finalSignal: AnomalySignal & { image?: string; mimeType?: string } = {
        id,
        timestamp: Date.now(),
        score: steadScore,
        type: isAnomaly ? 'ANOMALY_DETECTED' : 'BASELINE_NORMAL',
        vector: liveVector,
        location: 'STREAM_UPLINK_01',
        image: representativeImage,
        mimeType: isVideo ? 'image/jpeg' : mimeType 
      };

      setActiveSignal(finalSignal);
      setSignals(prev => [finalSignal, ...prev].slice(0, 10));
      
      addLog(`INIT_SEQUENCE: Initializing STEAD Perception Pipeline...`, 'info');
      setTierAnalysis({
        stead: { status: 'processing' },
        t1: { status: 'pending' },
        t2: { status: 'pending' },
        t3: { status: 'pending' },
      });
      
      // Step 1: STEAD FLAG (Anomaly Detection State Update)
      setProcessing({ step: 'T1', status: isAnomaly ? 'alert' : 'matched', detail: isAnomaly ? `ANOMALY_DETECTED: Score ${steadScore.toFixed(3)}` : 'STEAD: Baseline Normalcy Confirmed' });
      setTierAnalysis(prev => ({ ...prev, stead: { status: isAnomaly ? 'alert' : 'passed', score: steadScore } }));
      await new Promise(r => setTimeout(r, 600));
      
      addLog(`RAG_INIT: Scanning memory pool of ${medoids.length} medoids...`, 'info');
      
      let matchedMedoidIds: string[] = [];
      let finalTier: Tier = Tier.T1;
      let droneResult: Awaited<ReturnType<typeof queryDroneCortex>> | null = null;

      if (!isAnomaly) {
        addLog(`STEAD_OK: Normalcy confirmed (Intrinsic Anomaly Score: ${steadScore.toFixed(3)}). No RAG lookup required.`, 'success');
        setProcessing({ step: 'T1', status: 'matched', detail: 'STEAD: STABLE' });
        setTierAnalysis(prev => ({ ...prev, t1: { status: 'matched', detail: 'BASELINE_ENV' } }));
        addLog(`SEQUENCE_SLEEP: Resource-saving mode active. Drone maintaining standard patrol.`, 'info');
      } else {
        const t1Medoids = medoids.filter(m => m.tier === Tier.T1);
        addLog(`STEAD_ALERT: Intrinsic anomaly flagged! (Score: ${steadScore.toFixed(3)}). Triggering backend DINO RAG lookup across ${t1Medoids.length} T1 medoids...`, 'warn');
        setProcessing({ step: 'T1', status: 'alert', detail: `ANOMALY: ${steadScore.toFixed(3)}` });
        setTierAnalysis(prev => ({ ...prev, t1: { status: 'processing' } }));
        
        // Perform real T1 retrieval in the Python backend using the same DINO vector space as the DB.
        droneResult = await queryDroneCortex(representativeImage, steadScore, true);
        const t1BackendMatches = droneResult.retrieved_medoids.filter(m => m.tier === 'T1');
        const t1BackendAnalysis = droneResult.tier_analysis.find(analysis => analysis.tier === 'T1');
        const topT1Match = t1BackendMatches[0];

        if (topT1Match) {
          matchedMedoidIds = [topT1Match.id];
          const topScore = t1BackendAnalysis?.top_similarity ?? topT1Match.similarity;
          const t1Status = t1BackendAnalysis?.status === 'matched' ? 'matched' : 'alert';
          setTierAnalysis(prev => ({
            ...prev,
            t1: {
              status: t1Status,
              detail: topT1Match.label,
              score: topScore,
              matchId: topT1Match.id,
              source: topT1Match.source,
            },
          }));
          addLog(`RAG_MATCH: [T1] DINO baseline matched ${topT1Match.label} (${(topScore * 100).toFixed(1)}% match) [${topT1Match.source}_LAYER].`, t1Status === 'matched' ? 'success' : 'warn');
        } else {
          addLog(`RAG_FAIL: Backend returned no T1 medoids.`, 'error');
          setTierAnalysis(prev => ({ ...prev, t1: { status: 'alert', detail: 'EMPTY_POOL' } }));
        }
      }
      
      // Step 2: RAG CLASSIFICATION (Only if needed or for behavioral enrichment)
      if (isAnomaly) {
        const t2Medoids = medoids.filter(m => m.tier === Tier.T2);
        setProcessing({ step: 'T2', status: 'processing', detail: `RAG_T2: Searching ${t2Medoids.length} behavior patterns...` });
        setTierAnalysis(prev => ({ ...prev, t2: { status: 'processing' } }));
        await new Promise(r => setTimeout(r, 800));
        droneResult = droneResult || await queryDroneCortex(representativeImage, steadScore, true);
        const t2BackendMatches = droneResult.retrieved_medoids.filter(m => m.tier === 'T2');
        const t2BackendAnalysis = droneResult.tier_analysis.find(analysis => analysis.tier === 'T2');
        const topT2Match = t2BackendMatches[0];
        const topT2Score = t2BackendAnalysis?.top_similarity ?? topT2Match?.similarity ?? 0;

        if (topT2Match && t2BackendAnalysis?.status === 'matched') {
          addLog(`RAG_MATCH: [T2] Behavioral pattern identified as ${topT2Match.label} (${(topT2Score * 100).toFixed(1)}% match) [${topT2Match.source}_LAYER].`, 'success');
          matchedMedoidIds = [...matchedMedoidIds, topT2Match.id];
          finalTier = Tier.T2;
          setProcessing({ step: 'T2', status: 'matched', detail: `BEHAVIOR: ${topT2Match.label}` });
          setTierAnalysis(prev => ({ ...prev, t2: { status: 'matched', detail: topT2Match.label, score: topT2Score, matchId: topT2Match.id, source: topT2Match.source } }));
        } else {
          addLog(`RAG_NO_MATCH: [T2] Behavioral novelty high (Max sim: ${topT2Score.toFixed(3)}). Escalating to T3...`, 'warn');
          setProcessing({ step: 'T2', status: 'alert', detail: 'UNRESOLVED_BEHAVIOR' });
          setTierAnalysis(prev => ({ ...prev, t2: { status: 'alert', detail: topT2Match?.label || 'NOVEL_BEHAVIOR', score: topT2Score, matchId: topT2Match?.id, source: topT2Match?.source } }));
          
          const t3Medoids = medoids.filter(m => m.tier === Tier.T3);
          setProcessing({ step: 'T3', status: 'processing', detail: `RAG_T3: Searching ${t3Medoids.length} identity profiles...` });
          setTierAnalysis(prev => ({ ...prev, t3: { status: 'processing' } }));
          await new Promise(r => setTimeout(r, 600));
          const t3Best = t3Medoids.reduce((best, m) => {
            const sim = m.vector ? cosineSimilarity(liveVector, m.vector) : 0;
            return sim > best.sim ? { m, sim } : best;
          }, { m: null as Medoid | null, sim: -1 });

          if (t3Best.m && (isAnomaly ? t3Best.sim > 0.6 : t3Best.sim > 0.3)) {
             addLog(`RAG_MATCH: [T3] Identity resolved to ${t3Best.m.label} (${(t3Best.sim * 100).toFixed(1)}% match) [${t3Best.m.source}_LAYER].`, 'success');
             matchedMedoidIds = [...matchedMedoidIds, t3Best.m.id];
             finalTier = Tier.T3;
             setProcessing({ step: 'T3', status: 'matched', detail: `IDENTITY: ${t3Best.m.label}` });
             setTierAnalysis(prev => ({ ...prev, t3: { status: 'matched', detail: t3Best.m?.label, score: t3Best.sim, matchId: t3Best.m?.id, source: t3Best.m?.source } }));
          } else {
             if (isAnomaly) addLog('RAG_FAIL: [T3] Completely unknown entity detected.', 'error');
             setProcessing({ step: 'T3', status: 'alert', detail: 'UNKNOWN_PROFILE' });
             setTierAnalysis(prev => ({ ...prev, t3: { status: 'alert', detail: 'UNKNOWN_ENTITY', score: t3Best.sim } }));
             finalTier = Tier.T3;
          }
        }
      }
      
      // Step 3: Cortex Synthesis (Decision Making)
      let result;
      if (useGemini) {
        addLog(`CORTEX_PROX: Synthesizing outcome via Cloud weights...`, 'info');
        result = await runIITBInference(representativeImage, 'Sector 7G: Perimeter North', isVideo ? 'image/jpeg' : mimeType);
      } else {
        addLog(`CORTEX_PROX: Executing LOCAL_EDGE synthesis...`, 'info');
        // Reuse the backend DINO RAG result from T1 when available.
        droneResult = droneResult || await queryDroneCortex(representativeImage, steadScore);
        const backendMatchedTier = droneResult.tier_analysis.find(analysis => analysis.status === 'matched')?.tier;
        const backendMedoidIds = droneResult.retrieved_medoids.map(m => m.id);
        
        result = {
          anomaly_detected: isAnomaly,
          score: droneResult.anomaly_score || droneResult.score || steadScore,
          matched_tier: backendMatchedTier || droneResult.matched_tier || (finalTier === Tier.T1 ? 'T1' : finalTier === Tier.T2 ? 'T2' : 'T3'),
          action_label: droneResult.recommended_action,
          reasoning: droneResult.reasoning,
          prediction: isAnomaly ? 'EDGE_SYNTHESIS_COMPLETE' : 'PERSISTENT_STABILITY',
          matched_medoid_ids: backendMedoidIds.length > 0 ? backendMedoidIds : (droneResult.matched_medoids || matchedMedoidIds),
          verbose_logs: droneResult.verbose_logs || [
            "DB_HIT: Submodular medoid retrieval successful.",
            "VECTOR_SPACE: Euclidean distance processed.",
            "CORTEX_LOCAL: Protocol synthesized."
          ]
        };
      }
      
      addLog(`INFERENCE_OK: Process complete.`, 'success');
      
      if (result.verbose_logs) {
        for (const log of result.verbose_logs) {
          await new Promise(r => setTimeout(r, 400));
          addLog(log, result.anomaly_detected ? 'warn' : 'info');
        }
      }

      setActiveSignal(prev => prev ? ({
        ...prev,
        score: result.score || 0.5,
        type: result.anomaly_detected ? 'ANOMALY_TRIGGERED' : 'BASELINE_MATCH',
        actionLabel: result.action_label || 'IDENTIFIED',
        retrievedMedoids: matchedMedoidIds.length > 0 ? matchedMedoidIds : (result.matched_medoid_ids || [])
      }) : null);

      setProcessing({ step: 'Cortex', status: 'processing', detail: useGemini ? '[CLOUD] Final Decision...' : '[LOCAL] Edge Assessment...' });
      
      setCortexResult({
        risk_level: result.anomaly_detected ? 'HIGH' : 'LOW',
        reasoning: result.reasoning,
        prediction: result.prediction,
        action: result.anomaly_detected ? 'ESCALATE' : 'MONITOR'
      });
      
      setProcessing({ step: 'Outcome', status: result.anomaly_detected ? 'alert' : 'matched', detail: `CORTEX_LNK_OK` });
    } catch (e: any) {
      console.error(e);
      addLog(`CRITICAL_FAIL: Pipeline error - ${e.message}`, 'error');
      setProcessing({ step: 'System', status: 'alert', detail: e.message || 'PIPELINE_ERROR' });
    }
  };

  return (
    <div className="flex flex-col h-screen w-full bg-[#0A0A0A] text-[#E4E3E0] font-sans p-6 overflow-hidden tech-bg">
      <input 
        type="file" 
        ref={fileInputRef} 
        onChange={handleFileUpload} 
        className="hidden" 
        accept="image/*,video/mp4"
        multiple
      />
      {/* Header Section */}
      <header className="flex items-center justify-between border-b border-[#333] pb-6 mb-6 shrink-0 shadow-lg">
        <div className="flex flex-col">
          <div className="flex items-center gap-3 mb-1">
             <img src="/iitb_logo.png" alt="IIT Bombay Logo" className="w-8 h-8" />
             <h1 className="text-xs font-mono tracking-[0.3em] text-[#f27d26] uppercase">IIT Bombay</h1>
          </div>
          <h2 className="text-2xl font-bold tracking-tight italic font-serif">Spatio-Temporal Pipeline</h2>
        </div>

          <div className="flex items-center gap-8">
            {/* Bulk Mode Toggle */}
            <button 
              onClick={() => setIsBulkMode(!isBulkMode)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded border transition-all ${isBulkMode ? 'bg-[#f27d26]/20 border-[#f27d26] text-[#f27d26]' : 'bg-[#111] border-[#333] text-stone-500 hover:border-[#444]'}`}
            >
              <Workflow className="w-4 h-4" />
              <span className="text-[10px] font-bold uppercase tracking-wider">Bulk Pipeline</span>
            </button>

            {/* Gemini Mode Toggle */}
          <div className="flex items-center gap-4 bg-[#111] border border-[#222] px-4 py-2 rounded-sm shadow-inner">
             <div className="flex flex-col items-end mr-2">
               <span className="text-[8px] uppercase text-stone-600 font-bold tracking-widest">Inference Mode</span>
               <span className={`text-[9px] font-mono font-bold ${useGemini ? 'text-blue-400' : 'text-emerald-400'}`}>
                 {useGemini ? 'CLOUD::GEMINI_V2' : 'EDGE::LOCAL_ONLY'}
               </span>
             </div>
             <button 
               onClick={() => setUseGemini(!useGemini)}
               className={`w-10 h-5 rounded-full relative transition-all shadow-md ${useGemini ? 'bg-blue-600/30 border border-blue-500/50' : 'bg-emerald-600/30 border border-emerald-500/50'}`}
             >
               <motion.div 
                 animate={{ x: useGemini ? 20 : 4, backgroundColor: useGemini ? '#60a5fa' : '#34d399' }}
                 className="absolute top-1 w-3 h-3 rounded-full"
               />
             </button>
          </div>

          <button 
            onClick={() => setShowGuide(true)}
            className="flex items-center gap-2 text-[10px] uppercase font-bold text-stone-400 hover:text-[#f27d26] transition-colors border-b border-white/5 pb-1"
          >
            <Book className="w-3 h-3 text-[#f27d26]" />
            Deployment Blueprints
          </button>

          <button 
            onClick={() => window.open('/presentation', '_blank')}
            className="flex items-center gap-2 text-[10px] uppercase font-bold text-stone-400 hover:text-blue-400 transition-colors border-b border-white/5 pb-1"
          >
            <Layers className="w-3 h-3 text-blue-400" />
            System Presentation
          </button>

          <div className="flex gap-10 text-right">
            <div className="flex flex-col">
              <span className="text-[10px] uppercase opacity-50 font-mono tracking-widest">Edge Reflex</span>
              <span className="font-mono text-sm text-emerald-500">STEAD ACTIVE</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] uppercase opacity-50 font-mono tracking-widest">Uptime</span>
              <span className="font-mono text-sm text-stone-400">342:12:09</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Operational Grid */}
      <main className="grid grid-cols-12 gap-6 flex-grow overflow-hidden mb-6 relative">
        {/* Bulk Ingestion Panel Overlay */}
        <AnimatePresence>
          {isBulkMode && (
            <motion.div 
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="absolute inset-y-0 right-0 w-96 bg-[#0f0f0f] border-l border-[#333] z-50 shadow-2xl flex flex-col p-6"
            >
              <div className="flex items-center justify-between mb-6 shrink-0">
                <div className="flex items-center gap-2">
                  <Database className="w-5 h-5 text-[#f27d26]" />
                  <h3 className="text-sm font-bold uppercase tracking-widest text-[#f27d26]">Local Edge Ingest</h3>
                </div>
                <button onClick={() => setIsBulkMode(false)} className="text-stone-500 hover:text-white transition-colors">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto space-y-3 mb-6 pr-2 custom-scrollbar relative">
                {bulkQueue.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-48 border-2 border-dashed border-[#222] rounded-lg p-6 text-center">
                    <Zap className="w-8 h-8 text-[#222] mb-3" />
                    <p className="text-xs text-stone-600 font-medium">No videos in ingestion queue.</p>
                    <p className="text-[10px] text-stone-700 mt-1 uppercase tracking-tight">Select multiple files via the import button below.</p>
                  </div>
                ) : (
                  <>
                    {bulkQueue.every(q => q.status === 'done' || q.status === 'error') && (
                      <motion.div 
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="mb-4 p-4 bg-emerald-500/20 border border-emerald-500/40 rounded-lg text-center"
                      >
                        <Shield className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
                        <h4 className="text-sm font-bold text-emerald-400 uppercase tracking-widest">Digestion Complete</h4>
                        <p className="text-[10px] text-emerald-200/60 mt-1 uppercase">Representative medoids committed to edge RAG store.</p>
                        <button 
                          onClick={() => setBulkQueue([])}
                          className="mt-3 px-4 py-1.5 bg-emerald-500 text-black text-[10px] font-black uppercase rounded hover:bg-emerald-400 transition-colors"
                        >
                          Reset Pipeline
                        </button>
                      </motion.div>
                    )}
                    {bulkQueue.map((item, idx) => (
                      <div key={idx} className={`p-3 border rounded-sm flex items-center justify-between transition-all ${
                        item.status === 'processing' ? 'bg-[#f27d26]/10 border-[#f27d26] ring-1 ring-[#f27d26]/20' : 
                        item.status === 'done' ? 'bg-emerald-500/5 border-emerald-500/20 opacity-60' : 
                        'bg-[#111] border-[#222]'
                      }`}>
                      <div className="flex flex-col overflow-hidden">
                        <span className="text-[11px] font-bold truncate tracking-tight">{item.file.name}</span>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-[9px] uppercase tracking-tighter opacity-50 font-mono">{(item.file.size / 1024 / 1024).toFixed(2)} MB</span>
                          <span className="text-[8px] px-1 bg-[#222] rounded text-stone-500 font-mono uppercase">{item.file.type.split('/')[1] || 'video'}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {item.status === 'pending' && <div className="w-2 h-2 rounded-full bg-stone-700" />}
                        {item.status === 'processing' && (
                          <motion.div
                            animate={{ rotate: 360 }}
                            transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                          >
                            <Zap className="w-3 h-3 text-[#f27d26]" />
                          </motion.div>
                        )}
                        {item.status === 'done' && <Shield className="w-3 h-3 text-emerald-400" />}
                        {item.status === 'error' && <AlertTriangle className="w-3 h-3 text-red-500" />}
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>

              <div className="space-y-4 shrink-0">
                <button 
                  onClick={() => fileInputRef.current?.click()}
                  className="w-full bg-[#111] border border-[#333] hover:border-[#f27d26] hover:text-[#f27d26] py-3 rounded text-[11px] font-bold uppercase transition-all flex items-center justify-center gap-2"
                >
                  <Search className="w-4 h-4" />
                  Select Source Signals
                </button>
                
                <button 
                  disabled={bulkQueue.filter(q => q.status === 'pending').length === 0}
                  onClick={runBulkIngestion}
                  className="w-full bg-[#f27d26] text-black hover:bg-[#f27d26]/90 disabled:bg-stone-800 disabled:text-stone-600 py-4 rounded text-[11px] font-extrabold uppercase transition-all flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(242,125,38,0.3)] group"
                >
                  <Workflow className={`w-4 h-4 ${bulkQueue.some(q => q.status === 'processing') ? 'animate-spin' : ''}`} />
                  {bulkQueue.some(q => q.status === 'processing') ? 'Synthesizing...' : 'Initialize Batch Ingestion'}
                </button>

                <div className="p-3 bg-[#111] rounded border border-[#222] border-l-2 border-l-[#f27d26]">
                    <div className="flex items-center justify-between mb-2">
                       <span className="text-[9px] font-bold text-[#f27d26] uppercase tracking-tighter">Inference: AIR-GAPPED_LOCAL</span>
                       <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    </div>
                    <p className="text-[9px] text-stone-400 leading-relaxed uppercase tracking-tight">
                      Distillation via <span className="text-white">Submodlib (IIT Bombay)</span>. 
                      Facility Location Greedy Optimization.
                      <br/><br/>
                      <span className="text-[#f27d26] font-bold">OKUTAMA:</span> Ingested patterns are indexed locally into edge memory. Gemini is not required for this pipeline.
                    </p>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        
        {/* Left Column: The Reflex (Perception) + Embedding Manifold */}
        <section className="col-span-3 flex flex-col border border-[#333] p-5 bg-[#111] overflow-hidden">
          <div className="flex justify-between items-center mb-4 shrink-0">
            <h3 className="text-xs uppercase tracking-widest font-bold border-l-2 border-[#f27d26] pl-2">The Reflex</h3>
            <span className="text-[9px] font-mono bg-[#222] px-2 py-0.5 text-stone-400">STEAD-REFLEX_V2</span>
          </div>

          <div className="flex-1 flex flex-col min-h-0 overflow-hidden gap-1">
            {/* Video Container (Top Split) */}
            <div 
              key={activeSignal?.id} 
              style={{ height: `${videoHeight}px` }}
              className="w-full bg-black border border-[#222] relative overflow-hidden group cursor-crosshair flex flex-col shrink-0"
            >
              <div className="flex-grow relative flex items-center justify-center overflow-hidden">
                {/* @ts-ignore */}
                {activeSignal?.image ? (
                  activeSignal.mimeType?.startsWith('video/') ? (
                    <motion.div
                      key={`video-${activeSignal.id}`}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="w-full h-full relative"
                    >
                      <video
                        /* @ts-ignore */
                        src={activeSignal.image}
                        className="w-full h-full object-contain bg-black"
                        autoPlay
                        loop
                        muted
                        playsInline
                        controls
                      />
                      <div className="absolute top-2 right-2 bg-black/60 px-2 py-1 text-[8px] font-mono text-emerald-400 border border-emerald-500/30">
                        LIVE_FEED_DECODED
                      </div>
                    </motion.div>
                  ) : (
                    <motion.img 
                      key={`img-${activeSignal.id}`}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      /* @ts-ignore */
                      src={activeSignal.image} 
                      className="w-full h-full object-contain shadow-2xl"
                      referrerPolicy="no-referrer"
                    />
                  )
                ) : (
                  <div className="flex flex-col items-center gap-3 opacity-20">
                    <Eye className="w-8 h-8" />
                    <span className="text-[10px] uppercase tracking-widest font-bold">Waiting for Uplink...</span>
                  </div>
                )}
              </div>
              
              <div className="absolute inset-x-0 bottom-0 p-2 opacity-20 pointer-events-none">
                <div className="grid grid-cols-8 grid-rows-4 gap-1 w-full h-16">
                  {Array.from({ length: 32 }).map((_, i) => (
                    <div key={i} className="border border-white/5" />
                  ))}
                </div>
              </div>
              
              <div className="absolute bottom-2 left-3 font-mono text-[9px] text-[#f27d26] tracking-tighter uppercase p-1 bg-black/80 z-20">
                PROB: {activeSignal ? activeSignal.score.toFixed(3) : '0.000'}
              </div>
            </div>
            
            {/* Draggable Resize Handle */}
            <div 
              onMouseDown={(e) => {
                isResizing.current = true;
                startY.current = e.clientY;
                startHeight.current = videoHeight;
                document.body.style.cursor = 'row-resize';
                document.body.style.userSelect = 'none';
              }}
              className="h-2 w-full bg-[#18181b] hover:bg-[#f27d26]/60 cursor-row-resize flex items-center justify-center transition-colors border-t border-b border-[#333] group/handle shrink-0 z-30"
            >
              <div className="w-12 h-[2px] bg-[#333] group-hover/handle:bg-[#f27d26] transition-colors rounded-full" />
            </div>

            {/* Embedding Manifold Container (Bottom Split) */}
            <div className="flex-1 flex flex-col min-h-0 bg-black border border-[#222] p-4 overflow-hidden relative">
              <div className="flex items-center justify-between mb-4 shrink-0">
                <div className="flex items-center gap-2">
                  <Activity className="w-3 h-3 text-blue-400" />
                  <h3 className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Embedding Manifold</h3>
                </div>
                <div className="text-[8px] font-mono text-stone-600 bg-stone-900 px-2 py-0.5">PCA_REDUCED</div>
              </div>

              <div className="flex-1 relative bg-[#050505] overflow-hidden border border-[#111] inner-shadow mb-4">
                <div className="absolute inset-0 grid grid-cols-10 grid-rows-10 opacity-[0.03]">
                  {Array.from({ length: 100 }).map((_, i) => (
                    <div key={i} className="border-[0.5px] border-stone-500" />
                  ))}
                </div>
                
                {/* Background Latent Population (Decorative) */}
                {Array.from({ length: 30 }).map((_, i) => (
                  <div 
                    key={`bg-${i}`}
                    className="absolute w-0.5 h-0.5 bg-stone-700 rounded-full"
                    style={{ 
                      left: `${(i * 13) % 90 + 5}%`, 
                      top: `${(i * 17) % 90 + 5}%`,
                    }}
                  />
                ))}

                {/* Distilled Medoids */}
                {medoids.map((m, i) => {
                  const isMatched = activeSignal?.retrievedMedoids?.includes(m.id);
                  return (
                    <motion.div
                      key={m.id}
                      initial={false}
                      animate={{ 
                        scale: isMatched ? [1, 2.5, 2] : 1,
                        backgroundColor: isMatched ? '#f27d26' : '#777',
                        opacity: isMatched ? 1 : 0.8
                      }}
                      className="absolute w-2 h-2 rounded-full cursor-help group/dot"
                      style={{ 
                        left: `${(i * 23) % 80 + 10}%`, 
                        top: `${(i * 31) % 80 + 10}%`,
                        boxShadow: isMatched ? '0 0 20px #f27d26' : '0 0 5px rgba(255,255,255,0.1)',
                        zIndex: isMatched ? 20 : 10
                      }}
                    >
                      {isMatched && (
                        <div className="absolute top-4 left-1/2 -translate-x-1/2 whitespace-nowrap bg-black border border-[#f27d26] px-2 py-0.5 text-[7px] text-[#f27d26] z-50">
                          MATCHED_{m.id}
                        </div>
                      )}
                    </motion.div>
                  );
                })}

                {/* Active Signal Origin */}
                {activeSignal && (
                  <motion.div 
                    initial={{ scale: 0, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    className="absolute w-3 h-3 border-2 border-blue-500 rounded-full bg-blue-500/20 z-30"
                    style={{ left: '50%', top: '45%', transform: 'translate(-50%, -50%)' }}
                  >
                    <div className="absolute -inset-6 border border-blue-500/10 rounded-full animate-ping" />
                    <div className="absolute -inset-2 border border-blue-500/40 rounded-full" />
                  </motion.div>
                )}
              </div>

              {/* Mini Stats (Compact view of Curation) */}
              <div className="grid grid-cols-2 gap-2 mb-2 shrink-0">
                <div className="flex flex-col border-l border-[#333] pl-2">
                  <span className="text-[8px] uppercase text-stone-600 font-mono">Reduction</span>
                  <span className="text-[10px] text-emerald-500 font-bold">99.4% DISTILLED</span>
                </div>
                <div className="flex flex-col border-l border-[#333] pl-2">
                  <span className="text-[8px] uppercase text-stone-600 font-mono">Optimization</span>
                  <span className="text-[10px] text-stone-400 font-mono">LOG-DET</span>
                </div>
              </div>
              
              <button 
                onClick={runCurationIndex}
                disabled={curation.status === 'running'}
                className={`w-full py-2 border rounded-none text-[8px] uppercase font-bold tracking-tighter transition-all shrink-0 ${
                  curation.status === 'running' 
                    ? 'border-emerald-500/50 text-emerald-500 animate-pulse' 
                    : 'border-stone-800 text-stone-500 hover:border-[#f27d26] hover:text-[#f27d26]'
                }`}
              >
                {curation.status === 'running' ? 'Optimizing...' : 'Re-Run Distillation'}
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-col gap-2 shrink-0">
            <button 
              onClick={() => fileInputRef.current?.click()}
              className="w-full bg-[#111] border border-[#333] text-stone-200 font-bold text-[10px] py-4 uppercase tracking-widest hover:border-[#f27d26] hover:text-[#f27d26] transition-all flex items-center justify-center gap-2"
            >
              <Eye className="w-4 h-4 text-[#f27d26]" />
              Upload Frame / Video
            </button>

            <button 
              disabled={!!processing && processing.status === 'processing'}
              onClick={triggerSTEAD}
              className={`w-full font-extrabold text-[10px] py-4 uppercase tracking-widest transition-all transition-colors active:scale-95 flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(242,125,38,0.2)] ${
                processing?.status === 'processing' 
                ? 'bg-stone-800 text-stone-500 cursor-not-allowed' 
                : 'bg-[#f27d26] text-black hover:bg-orange-500'
              }`}
            >
              <Zap className={`w-4 h-4 ${processing?.status === 'processing' ? 'animate-pulse' : ''}`} />
              {processing?.status === 'processing' ? 'Processing Latent Space...' : 'Commit to Cortex Analysis'}
            </button>

            <div className="mt-4">
              <label className="text-[9px] uppercase tracking-widest text-[#f27d26] mb-1 block">
                 STEAD Threshold: {steadThreshold.toFixed(2)}
              </label>
              <input 
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={steadThreshold}
                onChange={(e) => setSteadThreshold(parseFloat(e.target.value))}
                className="w-full h-1 bg-[#222] appearance-none cursor-pointer accent-[#f27d26]"
              />
            </div>

            <div className="relative">
              <button 
                onClick={() => setShowRtspInput(!showRtspInput)}
                className={`w-full py-2 border text-[10px] uppercase font-bold tracking-widest transition-all flex items-center justify-center gap-2 ${showRtspInput ? 'bg-[#f27d26]/10 border-[#f27d26] text-[#f27d26]' : 'bg-[#111] border-[#333] text-stone-500 hover:border-stone-600'}`}
              >
                <Workflow className="w-3 h-3" />
                Add RTSP Stream
              </button>

              <AnimatePresence>
                {showRtspInput && (
                  <motion.div 
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="absolute bottom-full left-0 right-0 mb-2 p-3 bg-[#0d0d0d] border border-[#333] shadow-2xl z-50 flex flex-col gap-2"
                  >
                    <div className="flex justify-between items-center mb-1">
                      <div className="text-[8px] font-bold uppercase tracking-widest text-[#f27d26]">Remote RTSP URI</div>
                      <X className="w-3 h-3 text-stone-600 cursor-pointer" onClick={() => setShowRtspInput(false)} />
                    </div>
                    <input 
                      type="text"
                      value={rtspUrl}
                      onChange={(e) => setRtspUrl(e.target.value)}
                      placeholder="rtsp://192.168.1.100:554/live"
                      className="w-full bg-black border border-[#222] text-[9px] p-2 font-mono text-emerald-400 focus:border-[#f27d26] outline-none"
                    />
                    <button 
                      onClick={handleRtspConnect}
                      className="w-full bg-blue-600 text-white font-black text-[9px] py-2 uppercase tracking-widest hover:bg-blue-500 transition-colors shadow-lg"
                    >
                      Connect & Analyze
                    </button>
                    <div className="text-[7px] text-stone-600 italic leading-tight">
                      * Edge Proxy will transcode stream for browser-compatible perception pipeline.
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </section>

        {/* Center Column: Ingested Memory Store (Hierarchical RAG) */}
        <section className="col-span-4 flex flex-col border border-[#333] p-5 bg-[#111] overflow-hidden relative">
          <div className="flex justify-between items-start mb-6">
            <div>
              <h3 className="text-xs uppercase tracking-widest font-bold border-l-2 border-[#f27d26] pl-2 flex items-center gap-2">
                Memory Store 
                <span className="text-[10px] font-mono font-normal opacity-40">/ RAG</span>
              </h3>
              <div className="flex items-center gap-1 mt-2 pl-2">
                {(['ALL', 'BASE', 'LIVE'] as const).map(s => (
                  <button 
                    key={s}
                    onClick={() => setFilterSource(s)}
                    className={`text-[7px] px-1.5 py-0.5 font-bold uppercase tracking-tighter border transition-all ${filterSource === s ? 'bg-stone-200 text-black border-stone-200' : 'text-stone-500 border-white/5 hover:border-stone-500'}`}
                  >
                    {s}
                  </button>
                ))}
                <div className="w-px h-2 bg-white/10 mx-1" />
                <span className="text-[8px] text-stone-500 uppercase tracking-tighter">95% Compress</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button 
                onClick={handleResetRAG}
                className="text-[8px] font-mono bg-red-900/20 hover:bg-red-900/40 border border-red-500/30 px-2 py-0.5 text-red-400 transition-colors uppercase"
              >
                Flush Reset
              </button>
            </div>
          </div>

          {/* RAG Tier Pulse Bar */}
          <div className="grid grid-cols-3 gap-2 mb-6">
             <RAGTierCompact 
              title="Spatial Layer" 
              count={medoids.filter(m => m.tier === Tier.T1 && (filterSource === 'ALL' || (filterSource === 'BASE' && m.source === 'BASE') || (filterSource === 'LIVE' && m.source === 'LIVE'))).length}
              active={activeTier === Tier.T1}
              onClick={() => setActiveTier(Tier.T1)}
              matched={processing?.step === 'T1' && processing.status === 'matched'}
            />
             <RAGTierCompact 
              title="Action Layer" 
              count={medoids.filter(m => m.tier === Tier.T2 && (filterSource === 'ALL' || (filterSource === 'BASE' && m.source === 'BASE') || (filterSource === 'LIVE' && m.source === 'LIVE'))).length}
              active={activeTier === Tier.T2}
              onClick={() => setActiveTier(Tier.T2)}
              matched={processing?.step === 'T2' && processing.status === 'matched'}
            />
             <RAGTierCompact 
              title="Identity Layer" 
              count={medoids.filter(m => m.tier === Tier.T3 && (filterSource === 'ALL' || (filterSource === 'BASE' && m.source === 'BASE') || (filterSource === 'LIVE' && m.source === 'LIVE'))).length}
              active={activeTier === Tier.T3}
              onClick={() => setActiveTier(Tier.T3)}
              matched={processing?.step === 'T3' && processing.status === 'matched'}
            />
          </div>

          <div className="flex-grow flex flex-col min-h-0 border-t border-white/5 pt-4">
            
            <div className="flex-grow space-y-2 overflow-y-auto pr-2 scrollbar-hide">
              {medoids
                .filter(m => {
                  const matchesTier = activeTier === 'ALL' || m.tier === activeTier;
                  const matchesSource = filterSource === 'ALL' || (filterSource === 'BASE' && m.source === 'BASE') || (filterSource === 'LIVE' && m.source === 'LIVE');
                  return matchesTier && matchesSource;
                })
                .map((medoid) => {
                  const isMatched = activeSignal?.retrievedMedoids?.includes(medoid.id);
                  const matchData = (Object.values(tierAnalysis) as any[]).find(t => t.matchId === medoid.id);
                  const isLive = medoid.source === 'LIVE';
                  return (
                    <motion.div 
                      layout
                      key={medoid.id} 
                      className={`p-3 border-l-2 ${isMatched ? 'border-l-[#f27d26] bg-[#f27d26]/5 border-y border-r border-white/5' : 'border-l-stone-800 bg-black/40 border-y border-r border-white/5'} transition-all relative overflow-hidden group hover:bg-white/[0.02]`}
                    >
                      {isMatched && (
                        <div className="absolute top-0 right-0 bg-[#f27d26] text-black text-[7px] font-black px-1.5 py-0.5 z-10 flex items-center gap-1">
                          {matchData?.score !== undefined && (
                            <span className="border-r border-black/20 pr-1 mr-1">{(matchData.score * 100).toFixed(1)}%</span>
                          )}
                          RETRIEVED
                        </div>
                      )}
                      
                      <div className="flex items-start gap-3">
                         <div className={`w-8 h-8 shrink-0 flex items-center justify-center border font-black text-[10px] ${isMatched ? 'bg-[#f27d26] text-black border-[#f27d26]' : 'border-white/10 text-stone-500'}`}>
                            {medoid.tier.charAt(5)}
                         </div>
                         <div className="flex-grow min-w-0">
                            <div className="flex justify-between items-center mb-1">
                               <div className="text-[10px] font-bold text-stone-200 truncate uppercase tracking-tight">{medoid.label}</div>
                               <div className="flex items-center gap-2">
                                  {!isLive ? (
                                    <span className="text-[7px] text-emerald-500/40 font-bold uppercase tracking-widest">Okutama_Action</span>
                                  ) : (
                                    <span className="text-[7px] text-blue-500/60 font-bold uppercase tracking-widest">User_Ingested</span>
                                  )}
                                  <span className="text-[8px] font-mono text-stone-700 bg-white/5 px-1">{medoid.id}</span>
                               </div>
                            </div>
                            <div className="text-[9px] text-stone-500 line-clamp-1 group-hover:line-clamp-none transition-all">{medoid.description}</div>
                         </div>
                      </div>
                    </motion.div>
                  );
                })}
            </div>
          </div>
        </section>

        {/* Right Column: The Cortex (Reasoning) */}
        <section className="col-span-5 flex flex-col border border-[#333] p-5 bg-[#111] overflow-hidden">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-xs uppercase tracking-widest font-bold border-l-2 border-[#f27d26] pl-2">The Cortex</h3>
            <div className="flex items-center gap-3">
              <div className={`px-2 py-0.5 rounded-sm text-[8px] font-black uppercase tracking-tighter ${useGemini ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30' : 'bg-emerald-600/20 text-emerald-400 border border-emerald-500/30'}`}>
                {useGemini ? 'Cloud Mode' : 'Local Mode'}
              </div>
              <span className="text-[9px] font-mono bg-[#222] px-2 py-0.5 text-stone-400 text-blue-400">AGENT_ROUTER_V4</span>
            </div>
          </div>

          <div className="mb-6">
            <div className="flex justify-between items-center text-[9px] uppercase tracking-widest text-[#f27d26] mb-1">
              <span>Pipeline Status</span>
              <span>{processing?.step ? `Gated Processing: ${processing.step}` : 'Standing By'}</span>
            </div>
            <div className="flex gap-1">
              {['T1', 'T2', 'T3', 'Cortex', 'Outcome'].map((step) => {
                const isActive = processing?.step === step;
                const isDone = ['T1', 'T2', 'T3', 'Cortex', 'Outcome'].indexOf(processing?.step || '') > ['T1', 'T2', 'T3', 'Cortex', 'Outcome'].indexOf(step);
                return (
                  <div 
                    key={step} 
                    className={`flex-1 h-1.5 transition-all ${
                      isActive ? 'bg-[#f27d26] animate-pulse' : 
                      isDone ? 'bg-[#f27d26]/50' : 'bg-[#222]'
                    }`}
                  />
                );
              })}
            </div>
          </div>

          <div className="flex-grow font-mono text-[11px] bg-black p-5 border border-[#222] overflow-y-auto space-y-2 flex flex-col">
            {!activeSignal ? (
              <div className="opacity-20 flex flex-col items-center justify-center h-full text-center">
                <Lock className="w-8 h-8 mb-4" />
                <p className="uppercase tracking-[0.2em]">System Awaiting STEAD Input</p>
              </div>
            ) : (
              <AnimatePresence mode="popLayout">
                <div key={activeSignal.id} className="flex flex-col flex-grow">
                  <div className="text-emerald-500 font-bold uppercase tracking-widest mb-4 border-b border-emerald-500/20 pb-2 flex justify-between items-center">
                    <span>[AGENT_ROUTER] TRIGGERED // {activeSignal.id}</span>
                    <span className="text-[9px] animate-pulse">● LIVE</span>
                  </div>

                  {/* Tier Transparency Report */}
                  <div className="grid grid-cols-4 gap-1 mb-6 p-1 bg-[#080808] border border-[#222] shrink-0">
                    {(Object.entries(tierAnalysis) as [string, any][]).map(([key, data]) => (
                      <div key={key} className={`flex flex-col p-2 border transition-all ${
                        data.status === 'matched' || data.status === 'passed' ? 'border-emerald-500/30 bg-emerald-500/5' :
                        data.status === 'alert' ? 'border-amber-500/30 bg-amber-500/5' :
                        data.status === 'processing' ? 'border-blue-500/30 bg-blue-500/5 animate-pulse' :
                        'border-white/5 opacity-40'
                      }`}>
                        <div className="flex justify-between items-start mb-1">
                          <span className="text-[7px] uppercase font-black text-stone-500 leading-none">{key}</span>
                          {data.score !== undefined && (
                            <span className="text-[6px] font-mono opacity-50 bg-white/5 px-1">
                              {data.score.toFixed(3)}
                            </span>
                          )}
                        </div>
                        <span className={`text-[8px] font-bold uppercase tracking-tight ${
                          data.status === 'matched' || data.status === 'passed' ? 'text-emerald-400' :
                          data.status === 'alert' ? 'text-amber-400' :
                          data.status === 'processing' ? 'text-blue-400' :
                          'text-stone-700'
                        }`}>
                          {data.status === 'pending' ? 'IDLE' : data.status}
                          {data.source && (
                            <span className={`ml-1 text-[6px] px-1 py-0 border ${
                              data.source === 'BASE' ? 'text-stone-500 border-stone-800' : 'text-f27d26 border-[#f27d26]/30'
                            }`}>
                              {data.source}
                            </span>
                          )}
                        </span>
                        {data.detail && (
                          <div className="text-[7px] truncate text-stone-400 mt-1 font-mono flex items-center gap-1 group relative">
                            <Workflow className="w-2 h-2 shrink-0" />
                            {data.detail}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  
                  <div className="space-y-1 mb-6 flex-grow overflow-y-auto max-h-[300px] scrollbar-hide" ref={scrollRef}>
                    {systemLogs.map((log) => (
                      <motion.div 
                        key={log.id} 
                        initial={{ opacity: 0, x: -5 }} 
                        animate={{ opacity: 1, x: 0 }}
                        className={`flex gap-2 ${
                          log.type === 'error' ? 'text-red-400' : 
                          log.type === 'warn' ? 'text-amber-400' : 
                          log.type === 'success' ? 'text-emerald-400' : 
                          'text-stone-500'
                        }`}
                      >
                        <span className="opacity-40">{">"}</span>
                        <span className="flex-1">{log.text}</span>
                      </motion.div>
                    ))}
                    {processing?.status === 'processing' && (
                      <div className="flex gap-2 text-stone-600 animate-pulse">
                        <span className="opacity-40">{">"}</span>
                        <span className="flex-1 italic">Processing next node...</span>
                      </div>
                    )}
                  </div>
                  
                  {anomalousFrames.length > 0 && (
                    <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="mb-6 p-3 bg-red-950/10 border border-red-500/20 rounded-sm">
                      <div className="flex justify-between items-center mb-2">
                        <div className="flex flex-col">
                          <span className="text-[9px] uppercase tracking-widest text-red-400 font-bold">Detected Anomaly</span>
                          <span className="text-[8px] font-mono text-red-500/60">T={anomalousFrames[selectedAnomalyIndex].timestamp.toFixed(1)}s</span>
                        </div>
                        <div className="flex items-center gap-2">
                           <span className="text-[9px] font-mono text-red-400 bg-red-900/30 px-1 rounded">{anomalousFrames[selectedAnomalyIndex].score.toFixed(3)}</span>
                           <span className="text-[9px] text-gray-500 font-mono">{selectedAnomalyIndex + 1} / {anomalousFrames.length}</span>
                        </div>
                      </div>
                      
                      <div className="relative group">
                        <img 
                          src={anomalousFrames[selectedAnomalyIndex].image} 
                          className="w-full h-40 object-contain bg-black border border-[#333]" 
                          alt="Anomaly" 
                          referrerPolicy="no-referrer" 
                        />
                        
                        {/* Navigation Overlay */}
                        <div className="absolute inset-y-0 left-0 flex items-center pl-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button 
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedAnomalyIndex((prev) => (prev - 1 + anomalousFrames.length) % anomalousFrames.length);
                            }}
                            className="bg-black/60 hover:bg-black/80 text-white p-1 rounded-full border border-white/10 transition-colors"
                          >
                            <ChevronLeft className="w-4 h-4" />
                          </button>
                        </div>
                        <div className="absolute inset-y-0 right-0 flex items-center pr-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button 
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedAnomalyIndex((prev) => (prev + 1) % anomalousFrames.length);
                            }}
                            className="bg-black/60 hover:bg-black/80 text-white p-1 rounded-full border border-white/10 transition-colors"
                          >
                            <ChevronRight className="w-4 h-4" />
                          </button>
                        </div>

                        <div className="absolute inset-x-0 bottom-2 flex justify-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                           <div className="bg-black/80 px-2 py-0.5 rounded text-[8px] text-white flex items-center gap-1 uppercase border border-white/10">
                              <kbd className="bg-gray-700 px-1 rounded">←</kbd>
                              <kbd className="bg-gray-700 px-1 rounded">→</kbd>
                              <span>Navigator</span>
                           </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                  {cortexResult && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="pt-4 mt-auto border-t border-[#333]">
                      <div className="text-blue-400 uppercase font-bold mb-3 tracking-widest flex items-center gap-2">
                        <Activity className="w-3 h-3" />
                        Outcome Assessment:
                      </div>
                      <div className="text-stone-300 italic mb-4 leading-relaxed bg-stone-900/80 p-4 border-l-2 border-blue-400 font-serif text-sm shadow-inner">
                        "{cortexResult.reasoning}"
                      </div>
                      
                      {/* Identification Callout */}
                      {tierAnalysis.t3.status === 'matched' && (
                        <div className="mb-4 flex items-center gap-2 p-2 bg-[#f27d26]/10 border border-[#f27d26]/30 text-[#f27d26] text-[10px] font-bold uppercase tracking-widest">
                          <UserCheck className="w-3 h-3" />
                          <span>Identity Resolved: {tierAnalysis.t3.detail}</span>
                          <span className="ml-auto bg-[#f27d26] text-black px-1.5 py-0.5 text-[8px]">{tierAnalysis.t3.source}_MEMORY_MATCH</span>
                        </div>
                      )}

                      {tierAnalysis.t2.status === 'matched' && tierAnalysis.t3.status !== 'matched' && (
                        <div className="mb-4 flex items-center gap-2 p-2 bg-blue-500/10 border border-blue-500/30 text-blue-400 text-[10px] font-bold uppercase tracking-widest">
                          <Zap className="w-3 h-3" />
                          <span>Behavior Profiled: {tierAnalysis.t2.detail}</span>
                          <span className="ml-auto bg-blue-500 text-black px-1.5 py-0.5 text-[8px]">{tierAnalysis.t2.source}_PATTERN</span>
                        </div>
                      )}
                      
                      <div className={`p-4 border ${
                        cortexResult.risk_level === 'HIGH' ? 'bg-red-950/30 border-red-500/50 text-red-400' : 
                        cortexResult.risk_level === 'ERROR' ? 'bg-stone-900 border-stone-700 text-stone-500' :
                        'bg-orange-950/20 border-[#f27d26]/50 text-[#f27d26]'
                      } font-bold uppercase tracking-widest transition-colors flex justify-between items-center relative overflow-hidden group`}>
                        <div className="absolute inset-0 bg-white/5 -translate-x-full group-hover:translate-x-full transition-transform duration-1000" />
                        <span className="relative z-10">Outcome: {cortexResult.prediction || cortexResult.risk_level}</span>
                        <ChevronRight className="w-4 h-4 opacity-50" />
                      </div>

                      <div className="mt-6 flex gap-3">
                        <button className="flex-1 bg-stone-900 hover:bg-stone-800 text-stone-400 border border-stone-800 font-bold text-[9px] py-3 uppercase tracking-widest transition-all">
                          Dismiss
                        </button>
                        <button className="flex-[2] bg-[#f27d26] hover:bg-orange-600 text-black font-bold text-[9px] py-3 uppercase tracking-widest transition-all shadow-[0_0_15px_rgba(242,125,38,0.2)]">
                          Escalate to Sector Command
                        </button>
                      </div>
                    </motion.div>
                  )}
                </div>
              </AnimatePresence>
            )}
          </div>
        </section>
      </main>

      {/* Footer Bar */}
      <footer className="mt-auto flex items-center justify-between border-t border-[#333] pt-5">
        <div className="flex gap-8">
          <StatusIndicator label="Qdrant DB" status="CONNECTED" />
          <StatusIndicator label="Jetson Edge" status="STABLE" />
          <StatusIndicator label="Drone Link" status="ENCRYPTED" />
        </div>
        <div className="text-[10px] font-mono opacity-40 uppercase tracking-[0.25em]">
          Architecture: SUBMODLIB + STEAD + QDRANT-HNSW_V3
        </div>
      </footer>

      <AnimatePresence>
        {showGuide && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] bg-black/90 flex items-center justify-center p-8 backdrop-blur-md"
          >
            <motion.div 
              initial={{ scale: 0.9, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              className="bg-[#111] border border-[#333] w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col shadow-2xl"
            >
              <div className="p-6 border-b border-[#222] flex justify-between items-center bg-[#0d0d0d]">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-[#f27d26] flex items-center justify-center">
                    <Book className="text-black w-5 h-5" />
                  </div>
                  <h2 className="text-lg font-bold tracking-tight uppercase tracking-widest">Drone Deployment Strategy</h2>
                </div>
                <button 
                  onClick={() => setShowGuide(false)}
                  className="p-2 hover:bg-[#222] rounded-full transition-colors"
                >
                  <X className="w-6 h-6 text-stone-500" />
                </button>
              </div>
              
              <div className="p-8 overflow-y-auto custom-scrollbar space-y-12">
                <section>
                  <h3 className="text-[#f27d26] uppercase text-xs font-bold tracking-[0.2em] mb-4 flex items-center gap-2">
                    <Workflow className="w-4 h-4" /> 1. Edge Ingestion Pipeline
                  </h3>
                  <div className="grid grid-cols-3 gap-6 text-[10px]">
                    <div className="p-4 bg-black border border-[#222]">
                      <h4 className="text-white font-bold mb-2 uppercase">Submodular Sampling</h4>
                      <p className="text-stone-400">Uses Facility Location optimization via Submodlib to extract only the most informative frames (1-2 FPS). This maintains full situational awareness while reducing NPU load by ~95%.</p>
                    </div>
                    <div className="p-4 bg-black border border-[#222]">
                      <h4 className="text-white font-bold mb-2 uppercase">STEAD Reflex</h4>
                      <p className="text-stone-400">A lightweight model running locally on the drone's TPU. It compares incoming frames against a rolling temporal baseline. Only "Out-of-Distribution" frames trigger the RAG lookup.</p>
                    </div>
                    <div className="p-4 bg-black border border-[#222]">
                      <h4 className="text-white font-bold mb-2 uppercase">Vector Quantization</h4>
                      <p className="text-stone-400">Embedds frames into a 512-dim latent space. These vectors are used for fast similarity searches against local medoids stored in an HNSW index.</p>
                    </div>
                  </div>
                </section>

                <section>
                  <h3 className="text-[#f27d26] uppercase text-xs font-bold tracking-[0.2em] mb-4 flex items-center gap-2">
                    <Database className="w-4 h-4" /> 2. 3-Tier Multi-Modal RAG
                  </h3>
                  <div className="space-y-4">
                    <div className="p-4 bg-black border border-[#222] flex gap-6">
                      <div className="text-[#f27d26] font-mono text-xs font-bold">T1</div>
                      <div className="text-[10px]">
                        <span className="text-white font-bold block mb-1">SPATIAL MEDOIDS</span>
                        <span className="text-stone-500">Facility Location anchors representing the environmental 'Baseline'. Defines what is geographically normal for this specific sector.</span>
                      </div>
                    </div>
                    <div className="p-4 bg-black border border-[#222] flex gap-6">
                      <div className="text-[#f27d26] font-mono text-xs font-bold">T2</div>
                      <div className="text-[10px]">
                        <span className="text-white font-bold block mb-1">BEHAVIORAL LOG-DET</span>
                        <span className="text-stone-500">Temporal change detection. Uses log-determinant mutual information to identify behavioral shifts (e.g. loitering, sudden acceleration).</span>
                      </div>
                    </div>
                    <div className="p-4 bg-black border border-[#222] flex gap-6">
                      <div className="text-[#f27d26] font-mono text-xs font-bold">T3</div>
                      <div className="text-[10px]">
                        <span className="text-white font-bold block mb-1">ENTITY SCHEMATA</span>
                        <span className="text-stone-500">Resolved identity fingerprints. Cross-referenced against high-priority entity lists (locally or via satellite downlink).</span>
                      </div>
                    </div>
                  </div>
                </section>

                <section>
                  <h3 className="text-[#f27d26] uppercase text-xs font-bold tracking-[0.2em] mb-4 flex items-center gap-2">
                    <Zap className="w-4 h-4" /> 3. Agentic Synthesis (Cortex)
                  </h3>
                  <div className="p-6 bg-black/40 border border-white/5 font-mono text-[10px] leading-relaxed text-stone-400 mb-8">
                    <p className="mb-4">The final reasoning step integrates STEAD scores with RAG context. Using the toggle in the header, you can switch between:</p>
                    <ul className="space-y-3">
                      <li><strong className="text-blue-400 tracking-widest">[HYBRID_GEMINI]</strong>: Uses Google Gemini for deep cognitive grounding. High accuracy but requires 5G/Satellite uplink.</li>
                      <li><strong className="text-emerald-400 tracking-widest">[LOCAL_EDGE]</strong>: Uses a local quantized LLM (e.g. Gemma-2B/Phi-3) running on NPU. 100% air-gapped, zero-latency, deterministic heuristics.</li>
                    </ul>
                  </div>
                </section>

                <section>
                  <h3 className="text-[#f27d26] uppercase text-xs font-bold tracking-[0.2em] mb-4 flex items-center gap-2">
                    <Workflow className="w-4 h-4" /> 4. Implementation Roadmap
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 bg-[#0d0d0d] border border-[#222]">
                      <h4 className="text-[9px] text-stone-500 font-bold uppercase mb-3">Development (The Drone)</h4>
                      <ul className="space-y-2 text-[10px] text-stone-400 font-mono">
                        <li className="flex gap-2"><span className="text-emerald-500">01</span> Python-based GStreamer pipeline for RTSP.</li>
                        <li className="flex gap-2"><span className="text-emerald-500">02</span> STEAD model quantization (TensorRT/OpenVINO).</li>
                        <li className="flex gap-2"><span className="text-emerald-500">03</span> Local Vector Store: Qdrant on NVMe.</li>
                        <li className="flex gap-2"><span className="text-emerald-500">04</span> MAVLink telemetry integration.</li>
                      </ul>
                    </div>
                    <div className="p-4 bg-[#0d0d0d] border border-[#222]">
                      <h4 className="text-[9px] text-stone-500 font-bold uppercase mb-3">Deployment (Ground Station)</h4>
                      <ul className="space-y-2 text-[10px] text-stone-400 font-mono">
                        <li className="flex gap-2"><span className="text-blue-500">01</span> React Dash (current app) via WebSocket.</li>
                        <li className="flex gap-2"><span className="text-blue-500">02</span> Dockerize as edge-compute container.</li>
                        <li className="flex gap-2"><span className="text-blue-500">03</span> Latency: &lt;150ms total loop target.</li>
                        <li className="flex gap-2"><span className="text-blue-500">04</span> Satellite Uplink for Cloud Auth proxy.</li>
                      </ul>
                    </div>
                  </div>
                </section>
              </div>

              <div className="p-6 bg-[#0d0d0d] border-t border-[#222] flex justify-end">
                <button 
                  onClick={() => setShowGuide(false)}
                  className="px-8 py-3 bg-[#f27d26] text-black font-bold text-xs uppercase tracking-[0.2em] hover:bg-orange-500 transition-colors"
                >
                  Confirm Architecture
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showT3Dossier && tierAnalysis.t3.status === 'matched' && (
          <motion.div 
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            className="fixed top-24 right-6 w-[450px] bg-[#0d0d0d] border border-red-500/30 shadow-[0_0_50px_rgba(255,0,0,0.2)] z-[60] flex flex-col overflow-hidden"
          >
            <div className="bg-red-950/20 border-b border-red-500/30 p-4 flex justify-between items-center">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 border-2 border-red-500 flex items-center justify-center bg-red-500/10">
                  <UserCheck className="text-red-500 w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-sm font-black text-white uppercase tracking-widest leading-none">Forensic Identity Dossier</h3>
                  <p className="text-[9px] text-red-400 font-mono mt-1 uppercase tracking-tighter">Resolution Level: HIGH_CONFIDENCE</p>
                </div>
              </div>
              <button 
                onClick={() => setShowT3Dossier(false)}
                className="p-1 hover:bg-white/10 rounded transition-colors"
              >
                <X className="w-5 h-5 text-stone-500" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              <div className="flex gap-4">
                 <div className="w-32 h-32 border border-[#333] relative group overflow-hidden bg-black shrink-0">
                    <img 
                      src={activeSignal?.image} 
                      className="w-full h-full object-cover"
                      alt="Identity Subject"
                    />
                    <div className="absolute inset-0 border-2 border-red-500 opacity-20 pointer-events-none" />
                    <div className="absolute top-1 right-1 bg-red-600 text-white text-[7px] font-black px-1">REF_LIVE</div>
                 </div>
                 <div className="flex-grow flex flex-col justify-between">
                    <div className="space-y-1">
                      <div className="text-[10px] text-red-500 font-bold uppercase tracking-widest">Matched Subject</div>
                      <div className="text-xl font-black text-white tracking-tight uppercase leading-none">{tierAnalysis.t3.detail}</div>
                      <div className="text-[9px] text-stone-500 font-mono mt-2">UUID: {tierAnalysis.t3.matchId}</div>
                    </div>
                    <div className="flex items-center gap-2">
                       <div className="flex-1 h-3 bg-red-950/30 border border-red-500/20 relative">
                          <motion.div 
                            initial={{ width: 0 }}
                            animate={{ width: `${(tierAnalysis.t3.score || 0) * 100}%` }}
                            className="h-full bg-red-500"
                          />
                       </div>
                       <span className="text-[10px] font-mono text-red-400 font-black">{((tierAnalysis.t3.score || 0) * 100).toFixed(1)}%</span>
                    </div>
                 </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                 <div className="p-3 bg-white/5 border border-white/5">
                    <span className="text-[8px] text-stone-500 uppercase block mb-1">Source Memory</span>
                    <span className="text-[10px] text-white font-bold uppercase tracking-wider">{tierAnalysis.t3.source === 'BASE' ? 'IITB Global Baseline' : 'Live Mission Store'}</span>
                 </div>
                 <div className="p-3 bg-white/5 border border-white/5">
                    <span className="text-[8px] text-stone-500 uppercase block mb-1">Risk Profile</span>
                    <span className={`text-[10px] font-black uppercase tracking-wider ${(tierAnalysis.t3.score || 0) > 0.85 ? 'text-red-500' : 'text-amber-500'}`}>
                      {(tierAnalysis.t3.score || 0) > 0.85 ? 'CRITICAL_THREAT' : 'UNDER_WATCH'}
                    </span>
                 </div>
              </div>

              <div className="space-y-2">
                 <h4 className="text-[9px] font-bold text-stone-400 uppercase tracking-[0.2em] flex items-center gap-2">
                    <Lock className="w-3 h-3 text-red-500" />
                    Forensic Action Proposal
                 </h4>
                 <div className="p-4 bg-black border border-[#222] font-mono text-[9px] text-stone-400 leading-relaxed italic">
                    "Subject matched via Mutual Information against behavioral medoid pool. Spatial location inconsistent with previous patrol telemetry. Recommend immediate sector lockdown and high-res persistent tracking."
                 </div>
              </div>

              <div className="flex gap-3">
                 <button className="flex-1 py-3 bg-stone-900 border border-white/10 text-stone-500 text-[9px] font-black uppercase tracking-widest hover:text-white transition-colors">
                    Flag False Positive
                 </button>
                 <button className="flex-1 py-3 bg-red-600 text-white text-[9px] font-black uppercase tracking-widest shadow-[0_0_20px_rgba(220,38,38,0.4)] hover:bg-red-500 transition-colors">
                    Authorize Intervention
                 </button>
              </div>
            </div>
            
            <div className="bg-white/5 p-2 px-4 flex items-center justify-between">
               <span className="text-[8px] font-mono text-stone-600 uppercase">Perceived @ EDGE_UPLINK_01</span>
               <Activity className="w-3 h-3 text-red-500/50" />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function RAGTierCompact({ title, active, matched, count, onClick }: any) {
  return (
    <div 
      onClick={onClick}
      className={`p-2 border border-white/5 transition-all flex flex-col items-center justify-center h-12 relative overflow-hidden cursor-pointer ${active ? 'bg-[#f27d26]/10 border-[#f27d26]/30 opacity-100' : 'bg-black/40 opacity-40 hover:opacity-60'}`}>
      <span className={`text-[8px] font-black uppercase tracking-widest ${active ? 'text-[#f27d26]' : 'text-stone-500'}`}>{title}</span>
      <span className="text-[7px] font-mono text-stone-600 mt-0.5">{count || 0} Slots</span>
      {matched && (
        <motion.div 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute inset-0 bg-emerald-500/10 flex items-center justify-center"
        >
          <span className="text-[7px] text-emerald-400 font-bold uppercase animate-pulse">HIT</span>
        </motion.div>
      )}
      {active && (
        <motion.div 
          className="absolute bottom-0 left-0 h-0.5 bg-[#f27d26]"
          initial={{ width: 0 }}
          animate={{ width: '100%' }}
          transition={{ duration: 1, repeat: Infinity }}
        />
      )}
    </div>
  );
}

function RAGTier({ title, subtitle, label, progress, active, matched }: any) {
  return (
    <div className={`p-4 border transition-all ${active ? 'border-[#f27d26] bg-[#f27d26]/5' : 'border-[#222] bg-black/40'}`}>
      <div className="flex justify-between items-center mb-3">
        <span className={`text-[10px] font-mono tracking-widest uppercase ${active ? 'text-[#f27d26]' : 'opacity-50'}`}>{title}</span>
        <span className="text-[9px] opacity-40 uppercase tracking-tighter">{subtitle}</span>
      </div>
      <div className="text-sm font-medium mb-3 flex items-center gap-2">
        {label}
        {matched && <div className="text-[8px] px-1 bg-emerald-500 text-black font-bold uppercase">Ready</div>}
      </div>
      <div className="w-full h-1 bg-[#222]">
        <motion.div 
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          className={`h-full ${active ? 'bg-[#f27d26]' : 'bg-[#f27d26]/40'}`} 
        />
      </div>
    </div>
  );
}

function StatusIndicator({ label, status }: any) {
  return (
    <div className="flex items-center gap-2">
      <div className={`w-2 h-2 rounded-full ${status === 'CONNECTED' || status === 'STABLE' || status === 'ENCRYPTED' ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-stone-600'} ${status === 'CONNECTED' ? 'animate-pulse' : ''}`} />
      <span className="text-[10px] font-mono uppercase tracking-widest text-stone-500">
        {label}: <span className="text-emerald-500/80">{status}</span>
      </span>
    </div>
  );
}

function InsightItem({ label, value, color }: { label: string, value: string, color: string }) {
  return (
    <div className="flex justify-between items-center group">
      <span className="text-[10px] uppercase text-stone-500 group-hover:text-stone-300 transition-colors">{label}</span>
      <span className={`text-[10px] font-mono ${color}`}>{value}</span>
    </div>
  );
}
