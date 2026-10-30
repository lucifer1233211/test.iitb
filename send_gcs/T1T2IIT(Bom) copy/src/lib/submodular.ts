/**
 * Submodular Optimization Utilities - Enhanced TypeScript Engine
 * Inspired by Decile submodlib (Python implementation for data summarization)
 * 
 * This module implements core submodular functions and the CELF (Lazy Greedy)
 * maximization algorithm to provide industrial-grade subset selection.
 */

export enum SubmodularFunction {
  FACILITY_LOCATION = 'Facility Location',
  LOG_DETERMINANT = 'Log-Determinant',
  DISPARITY_SUM = 'Disparity Sum',
  SATURED_COVERAGE = 'Saturated Coverage',
  GRAPH_CUT = 'Graph Cut'
}

/**
 * Calculates cosine similarity between two vectors.
 */
export function cosineSimilarity(a: number[], b: number[]): number {
  if (!a || !b || a.length !== b.length) return 0;
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  if (normA === 0 || normB === 0) return 0;
  // Enforce range [0, 1] for typical submodular kernels
  return Math.max(0, Math.min(1, dotProduct / (Math.sqrt(normA) * Math.sqrt(normB))));
}

/**
 * Extracts a feature vector from a File (Image or Video)
 */
export async function extractFeatures(file: File, timestamp?: number): Promise<{ vector: number[], image: string }> {
  return new Promise((resolve) => {
    const isVideo = file.type.startsWith('video/');
    const url = URL.createObjectURL(file);
    
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      URL.revokeObjectURL(url);
      return resolve({ vector: Array(32).fill(0), image: '' });
    }

    // We'll use a larger canvas for the image return but keep 64x64 for feature extraction
    canvas.width = 320; 
    canvas.height = 180;

    if (isVideo) {
      const video = document.createElement('video');
      video.src = url;
      video.muted = true;
      video.playsInline = true;
      
      video.onloadeddata = () => {
        if (timestamp !== undefined) {
          video.currentTime = Math.min(timestamp, video.duration);
        } else {
          video.currentTime = Math.min(1, video.duration / 2); // Sample middle frame default
        }
      };
      
      video.onseeked = () => {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const frameImage = canvas.toDataURL('image/jpeg', 0.7);
        
        // Re-scale internal context or use a temporary canvas for 64x64 features
        const featCanvas = document.createElement('canvas');
        featCanvas.width = 64;
        featCanvas.height = 64;
        const featCtx = featCanvas.getContext('2d')!;
        featCtx.drawImage(video, 0, 0, 64, 64);
        
        resolve({ vector: getPixelFeatures(featCtx), image: frameImage });
        URL.revokeObjectURL(url);
        video.remove();
      };
      
      video.onerror = () => {
        URL.revokeObjectURL(url);
        resolve({ vector: Array(32).fill(0).map(() => Math.random() * 0.1), image: '' });
      };
    } else {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        const frameImage = canvas.toDataURL('image/jpeg', 0.7);
        
        const featCanvas = document.createElement('canvas');
        featCanvas.width = 64;
        featCanvas.height = 64;
        const featCtx = featCanvas.getContext('2d')!;
        featCtx.drawImage(img, 0, 0, 64, 64);

        resolve({ vector: getPixelFeatures(featCtx), image: frameImage });
        URL.revokeObjectURL(url);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve({ vector: Array(32).fill(0).map(() => Math.random() * 0.1), image: '' });
      };
      img.src = url;
    }
  });
}

function getPixelFeatures(ctx: CanvasRenderingContext2D): number[] {
  const imageData = ctx.getImageData(0, 0, 64, 64);
  const data = imageData.data;
  
  // High-Resolution Feature Extraction: 32 dimensions
  // [0..15]: 4x4 Spatial Intensity Grid
  // [16..23]: Horizontal Gradient Bins
  // [24..31]: Vertical Gradient Bins
  const features = Array(32).fill(0);
  
  // 1. Spatial Intensity (16 dimensions: 4x4 grid)
  const cellSize = 16;
  for (let cy = 0; cy < 4; cy++) {
    for (let cx = 0; cx < 4; cx++) {
      let intensitySum = 0;
      for (let y = 0; y < cellSize; y++) {
        for (let x = 0; x < cellSize; x++) {
          const px = cx * cellSize + x;
          const py = cy * cellSize + y;
          const i = (py * 64 + px) * 4;
          intensitySum += (data[i] + data[i+1] + data[i+2]) / 3;
        }
      }
      features[cy * 4 + cx] = intensitySum / (cellSize * cellSize * 255);
    }
  }

  // 2. Structural Complexity (16 dimensions split by orientation)
  // We apply a non-linear weight to emphasize sharper edges (Higher Grad = Higher weight in the vector)
  // We track localized gradient density with a boost for high-frequency changes
  const hBins = Array(8).fill(0);
  const vBins = Array(8).fill(0);
  
  for (let y = 1; y < 63; y++) {
    for (let x = 1; x < 63; x++) {
      const i = (y * 64 + x) * 4;
      const i_r = (y * 64 + (x + 1)) * 4;
      const i_d = ((y + 1) * 64 + x) * 4;
      
      const v = (data[i] + data[i+1] + data[i+2]) / 3;
      const vr = (data[i_r] + data[i_r+1] + data[i_r+2]) / 3;
      const vd = (data[i_d] + data[i_d+1] + data[i_d+2]) / 3;
      
      const hGrad = Math.abs(v - vr);
      const vGrad = Math.abs(v - vd);
      
      // We weight higher bins more significantly in the count to boost their contribution to the vector norm
      const hIdx = Math.floor(Math.min(7, hGrad / 32));
      const vIdx = Math.floor(Math.min(7, vGrad / 32));
      
      // NON-LINEAR BOOST: Sharper gradients (even if few) represent tool movement/burglary signs
      // Increased sensitivity (hIdx > 0, meaning grad >= 32)
      const boost = (hIdx > 0 || vIdx > 0) ? 6 : 1;
      
      hBins[hIdx] += (hIdx + 1) * boost; 
      vBins[vIdx] += (vIdx + 1) * boost;
    }
  }
  
  const hSum = hBins.reduce((a, b) => a + b, 0) || 1;
  const vSum = vBins.reduce((a, b) => a + b, 0) || 1;
  
  for (let i = 0; i < 8; i++) {
    features[16 + i] = hBins[i] / hSum;
    features[24 + i] = vBins[i] / vSum;
  }
  
  return features;
}

/**
 * measureIntrinsicAnomaly: Calculates an anomaly score without using a reference memory store.
 * Based on spectral entropy and spatial irregularity.
 */
export function measureIntrinsicAnomaly(vector: number[]): number {
  if (vector.length < 32) return 0;
  
  const intensityPart = vector.slice(0, 16);
  const hGradPart = vector.slice(16, 24);
  const vGradPart = vector.slice(24, 32);

  // 1. Spatial Irregularity (Local Variance)
  const avgIntensity = intensityPart.reduce((a, b) => a + b, 0) / 16;
  const intensityVar = intensityPart.reduce((a, b) => a + Math.pow(b - avgIntensity, 2), 0) / 16;
  const iVarScore = Math.sqrt(intensityVar) * 2.5; // Scale up

  // 2. High-Frequency Structural Focus
  // We look at the top 5 gradient bins (out of 8). 
  // In normal frames, these are near zero. In anomalies (tools, fighting), these rise.
  const highFreqSum = [...hGradPart.slice(3), ...vGradPart.slice(3)].reduce((a, b) => a + b, 0);
  const hfScore = Math.pow(highFreqSum, 0.5) * 1.5; // Square root to boost even small amounts of high-freq noise

  // 3. Structural Complexity (Distribution Entropy)
  const entropy = -[...hGradPart, ...vGradPart].reduce((acc, val) => {
    if (val <= 0.001) return acc;
    return acc + val * Math.log2(val);
  }, 0) / 16;
  const eScore = entropy * 0.4;

  // Final intrinsic score - Weighted heavily towards high-frequency structural noise
  const finalScore = (iVarScore * 0.2) + (hfScore * 0.6) + (eScore * 0.2);
  
  return Math.max(0, Math.min(0.999, finalScore));
}

/**
 * CELF (Cost-Effective Lazy Forward) Optimization
 * An efficient greedy implementation that uses a priority queue for submodular maximization.
 * Complexity: O(n log n) average compared to standard Greedy O(k*n).
 */
export function greedyMaximize(
  allVectors: number[][],
  k: number,
  type: SubmodularFunction
): number[] {
  if (k <= 0 || allVectors.length === 0) return [];
  if (k >= allVectors.length) return allVectors.map((_, i) => i);

  const n = allVectors.length;
  const selected: number[] = [];
  
  // Priority queue metadata: { index, gain, last_round_updated }
  // We'll use a simple sorted array for the PQ since k is usually small and n is manageable.
  let pq: { id: number, gain: number, round: number }[] = [];

  // Initial pass to populate PQ
  for (let i = 0; i < n; i++) {
    const gain = calculateGain(type, allVectors, [], i);
    pq.push({ id: i, gain, round: 0 });
  }

  // Sort initial PQ (descending gain)
  pq.sort((a, b) => b.gain - a.gain);

  let currentRound = 0;

  while (selected.length < k && pq.length > 0) {
    const best = pq.shift()!;
    
    // Lazy update: If this element hasn't been updated in the current round, re-calculate
    if (best.round < currentRound) {
      best.gain = calculateGain(type, allVectors, selected, best.id);
      best.round = currentRound;
      
      // Re-insert into PQ and re-sort
      let inserted = false;
      for (let i = 0; i < pq.length; i++) {
        if (best.gain >= pq[i].gain) {
          pq.splice(i, 0, best);
          inserted = true;
          break;
        }
      }
      if (!inserted) pq.push(best);
      
      // Peek again (don't increment round yet, we need to check the next top)
      continue;
    }

    // If it is updated, it's globally optimal for this round (submodularity property)
    selected.push(best.id);
    currentRound++;
  }

  return selected;
}

function calculateGain(
  type: SubmodularFunction, 
  V: number[][], 
  selectedIdxs: number[], 
  candidateIdx: number
): number {
  const currentSet = selectedIdxs.map(i => V[i]);
  const newSetIdxs = [...selectedIdxs, candidateIdx];
  const newSet = [...currentSet, V[candidateIdx]];

  // Standard marginal gain calculation: f(S + {e}) - f(S)
  switch (type) {
    case SubmodularFunction.FACILITY_LOCATION:
      return facilityLocation(newSet, V) - facilityLocation(currentSet, V);
    case SubmodularFunction.LOG_DETERMINANT:
      return logDet(newSet) - logDet(currentSet);
    case SubmodularFunction.DISPARITY_SUM:
      return disparitySum(newSet) - disparitySum(currentSet);
    case SubmodularFunction.SATURED_COVERAGE:
      return saturatedCoverage(newSet, V) - saturatedCoverage(currentSet, V);
    case SubmodularFunction.GRAPH_CUT:
      return graphCut(newSetIdxs, V) - graphCut(selectedIdxs, V);
    default:
      return 0;
  }
}

/**
 * Facility Location Function (submodlib.FacilityLocationFunction)
 * f(S) = sum_{v in V} max_{s in S} sim(v, s)
 */
export function facilityLocation(S: number[][], V: number[][]): number {
  if (S.length === 0) return 0;
  let total = 0;
  for (const v of V) {
    let maxSim = 0;
    for (const s of S) {
      const sim = cosineSimilarity(s, v);
      if (sim > maxSim) maxSim = sim;
    }
    total += maxSim;
  }
  return total;
}

/**
 * Disparity Sum (Diversity)
 */
function disparitySum(S: number[][]): number {
  if (S.length < 2) return S.length;
  let total = 0;
  for (let i = 0; i < S.length; i++) {
    for (let j = i + 1; j < S.length; j++) {
      total += (1 - cosineSimilarity(S[i], S[j]));
    }
  }
  return total;
}

/**
 * Volume-based Log-Det approximation (Diversity)
 */
function logDet(S: number[][]): number {
  if (S.length === 0) return 0;
  if (S.length === 1) return 1;
  
  let avgDist = 0;
  for (let i = 0; i < S.length; i++) {
    let minDist = 1;
    for (let j = 0; j < S.length; j++) {
      if (i === j) continue;
      const d = 1 - cosineSimilarity(S[i], S[j]);
      if (d < minDist) minDist = d;
    }
    avgDist += minDist;
  }
  return avgDist;
}

/**
 * Saturated Coverage Function (submodlib.SaturatedCoverageFunction)
 * f(S) = sum_{v in V} min(sum_{s in S} sim(v, s), alpha)
 */
function saturatedCoverage(S: number[][], V: number[][], alpha: number = 0.5): number {
  if (S.length === 0) return 0;
  let total = 0;
  for (const v of V) {
    let coverage = 0;
    for (const s of S) {
      coverage += cosineSimilarity(s, v);
    }
    total += Math.min(coverage, alpha);
  }
  return total;
}

/**
 * Graph Cut Function (submodlib.GraphCutFunction)
 * f(S) = sum_{i in S, j in V} sim(i, j) - lambda * sum_{i, j in S} sim(i, j)
 */
function graphCut(S_idxs: number[], V: number[][], lambda: number = 0.7): number {
  if (S_idxs.length === 0) return 0;
  
  let term1 = 0;
  for (const i of S_idxs) {
    for (const j of V) {
      term1 += cosineSimilarity(V[i], j);
    }
  }
  
  let term2 = 0;
  for (const i of S_idxs) {
    for (const j of S_idxs) {
      term2 += cosineSimilarity(V[i], V[j]);
    }
  }
  
  return term1 - lambda * term2;
}
