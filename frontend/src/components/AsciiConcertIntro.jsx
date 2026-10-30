import { useEffect, useRef, useState } from 'react';

const RAMPS = {
  classic: ' .,:;-=+*#%@',
  portrait: ' .,:;i7rXZa2S80BWM@',
  crisp: ' .:-+#@',
  blocks: ' .·:░▒▓█',
};

// Default live tunable attributes — the reference page's shipped values.
const DEFAULTS = {
  speed: 2.5,
  smoothness: 0,
  bounce: 2.2,
  sway: 0.9,
  armSwing: 1.85,
  jumpHeight: 2.2,
  bodyScale: 1.05,
  headScale: 1.05,
  shoulderWidth: 1.05,
  waistWidth: 1.05,
  hipWidth: 1.05,
  limbThick: 1.3,
  armLength: 1.05,
  fingers: true,
  crowdCount: 14,
  singerScale: 0.9,
  stageHeight: 0.62,
  linePx: 5,
  rampKey: 'portrait',
  contrast: 0.95,
  spotlight: 2.2,
  lightSpeed: 2.5,
};

const SLIDER_BINDINGS = [
  { key: 'speed', label: 'Animation Speed (Tempo)', min: 0.1, max: 2.5, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'smoothness', label: 'Motion Smoothness (Damping)', min: 0, max: 0.97, step: 0.01, fmt: (v) => v.toFixed(2) },
  { key: 'bounce', label: 'Groove & Knee Bounce', min: 0, max: 2.2, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'sway', label: 'Torso & Hip Sway Range', min: 0, max: 2.2, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'armSwing', label: 'Arm Wave Amplitude', min: 0.1, max: 2, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'jumpHeight', label: 'Crowd Jump Height', min: 0, max: 2.2, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'bodyScale', label: 'Overall Human Height', min: 0.65, max: 1.45, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'headScale', label: 'Head & Neck Proportions', min: 0.7, max: 1.4, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'shoulderWidth', label: 'Shoulder Breadth', min: 0.7, max: 1.45, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'waistWidth', label: 'Waist Taper (V-Shape)', min: 0.65, max: 1.45, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'hipWidth', label: 'Hip & Pelvis Width', min: 0.7, max: 1.4, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'limbThick', label: 'Limb Muscle Thickness', min: 0.6, max: 1.6, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'armLength', label: 'Arm Bone Length', min: 0.75, max: 1.3, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'crowdCount', label: 'Crowd Dancers Count', min: 2, max: 14, step: 1, fmt: (v) => String(Math.round(v)), rebuildCrowd: true },
  { key: 'singerScale', label: 'Lead Singer Size', min: 0.75, max: 1.45, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'stageHeight', label: 'Stage Vertical Position', min: 0.45, max: 0.68, step: 0.01, fmt: (v) => v.toFixed(2) },
  { key: 'linePx', label: 'ASCII Line Size (Detail)', min: 5, max: 9.5, step: 0.5, fmt: (v) => `${v.toFixed(1)}px`, resize: true },
  { key: 'contrast', label: 'Body Shading Contrast', min: 0.6, max: 1.6, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'spotlight', label: 'Spotlight & Haze Intensity', min: 0, max: 2.2, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'lightSpeed', label: 'Spotlight Sweep Speed', min: 0, max: 2.5, step: 0.05, fmt: (v) => `${v.toFixed(2)}x` },
];

const GROUP_01 = ['speed', 'smoothness', 'bounce', 'sway', 'armSwing', 'jumpHeight'];
const GROUP_02 = [
  'bodyScale',
  'headScale',
  'shoulderWidth',
  'waistWidth',
  'hipWidth',
  'limbThick',
  'armLength',
];
const GROUP_03 = ['crowdCount', 'singerScale', 'stageHeight'];
const GROUP_04 = ['linePx', 'contrast', 'spotlight', 'lightSpeed'];
const BINDING_BY_KEY = Object.fromEntries(SLIDER_BINDINGS.map((b) => [b.key, b]));

const RAMP_OPTIONS = [
  { value: 'classic', label: 'Classic ( .,:;-=+*#%@ )' },
  { value: 'portrait', label: 'Portrait ( .,:;i7rXZa2S80BWM@ )' },
  { value: 'crisp', label: 'Crisp Minimal ( .:-+#@ )' },
  { value: 'blocks', label: 'Monochrome Blocks ( .·:░▒▓█ )' },
];

function defaultLabels() {
  return Object.fromEntries(SLIDER_BINDINGS.map((b) => [b.key, b.fmt(DEFAULTS[b.key])]));
}

export default function AsciiConcertIntro({ onGetStarted }) {
  const canvasRef = useRef(null);
  const cfg = useRef({ ...DEFAULTS });
  const crowdRef = useRef([]);
  const smoothedPosesRef = useRef({});
  const gridRef = useRef({
    cols: 200,
    rows: 115,
    charWidthPx: 3.9,
    lumBuf: new Float32Array(200 * 115),
    bodyIdBuf: new Int16Array(200 * 115),
    zBuf: new Float32Array(200 * 115),
  });
  const clockRef = useRef({ lastFrameMs: 0, animClock: 0, lightClock: 0 });
  const controlsRef = useRef({ rebuildCrowd: null, resizeCanvas: null });
  const leaveTimerRef = useRef(null);
  const leavingRef = useRef(false);

  const [values, setValues] = useState(defaultLabels);
  const [fingersOn, setFingersOn] = useState(DEFAULTS.fingers);
  const [rampKey, setRampKey] = useState(DEFAULTS.rampKey);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [status, setStatus] = useState('Ready to copy your settings');

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return undefined;

    const grid = gridRef.current;
    const crowd = crowdRef.current;
    const smoothedPoses = smoothedPosesRef.current;

    function getAspect() {
      return grid.charWidthPx / cfg.current.linePx;
    }

    function buildCrowd() {
      crowd.length = 0;
      const count = Math.max(2, Math.min(14, Math.round(cfg.current.crowdCount)));
      const leftCount = Math.floor(count / 2);
      const rightCount = count - leftCount;

      const buildTypes = ['lean', 'athletic', 'slender', 'broad'];

      // Distribute left side of floor (x in 0.07 .. 0.40)
      for (let i = 0; i < leftCount; i++) {
        const t = leftCount > 1 ? i / (leftCount - 1) : 0.5;
        const x = 0.08 + t * 0.32;
        const depthRow = i % 2;
        const footY = depthRow === 0 ? 0.9 : 0.96;
        const scale = depthRow === 0 ? 0.28 : 0.33;
        const z = depthRow === 0 ? 16 : 34;
        addPersonSlot(crowd.length, x, footY, scale, z, i % 8, buildTypes[i % 4]);
      }

      // Distribute right side of floor (x in 0.60 .. 0.92), leaving center open for the singer
      for (let i = 0; i < rightCount; i++) {
        const t = rightCount > 1 ? i / (rightCount - 1) : 0.5;
        const x = 0.6 + t * 0.32;
        const depthRow = (i + 1) % 2;
        const footY = depthRow === 0 ? 0.89 : 0.96;
        const scale = depthRow === 0 ? 0.28 : 0.33;
        const z = depthRow === 0 ? 16 : 34;
        addPersonSlot(crowd.length, x, footY, scale, z, (i + 4) % 8, buildTypes[(i + 2) % 4]);
      }
    }

    function addPersonSlot(idx, x, footY, scale, z, style, buildName) {
      let shWidth = 0.104;
      let chestWidth = 0.076;
      let waistWidth = 0.055;
      let hipWidth = 0.073;
      let limbThick = 1.0;

      if (buildName === 'broad') {
        shWidth = 0.116;
        chestWidth = 0.084;
        waistWidth = 0.062;
        hipWidth = 0.077;
        limbThick = 1.05;
      } else if (buildName === 'slender') {
        shWidth = 0.092;
        chestWidth = 0.068;
        waistWidth = 0.049;
        hipWidth = 0.07;
        limbThick = 0.9;
      } else if (buildName === 'athletic') {
        shWidth = 0.11;
        chestWidth = 0.08;
        waistWidth = 0.054;
        hipWidth = 0.074;
        limbThick = 1.02;
      }

      crowd.push({
        id: idx + 2,
        xNorm: x,
        footY,
        scale,
        zBase: z,
        style,
        tempoMul: 0.92 + (idx % 5) * 0.04,
        phase: idx * 1.35 + 0.4,
        shWidth,
        chestWidth,
        waistWidth,
        hipWidth,
        limbThick,
        headStyle: idx % 3,
      });
    }

    function resizeCanvas() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const lpx = cfg.current.linePx;
      ctx.font = `600 ${lpx}px "JetBrains Mono", monospace`;
      const measured = ctx.measureText('M').width;
      grid.charWidthPx = Math.max(3.0, measured > 0 ? measured : lpx * 0.6);

      grid.cols = Math.max(70, Math.floor(w / grid.charWidthPx));
      grid.rows = Math.max(55, Math.floor(h / lpx));

      grid.lumBuf = new Float32Array(grid.cols * grid.rows);
      grid.bodyIdBuf = new Int16Array(grid.cols * grid.rows);
      grid.zBuf = new Float32Array(grid.cols * grid.rows);
    }

    // Exponential pose smoothing helper so the user can dial in exact motion fluidity
    function smoothPoseState(key, targetPose, dt) {
      if (!smoothedPoses[key]) {
        smoothedPoses[key] = Object.assign({}, targetPose);
        return smoothedPoses[key];
      }
      const cur = smoothedPoses[key];
      // Map cfg.smoothness (0..0.97) to exponential decay rate
      const alpha =
        cfg.current.smoothness <= 0.01
          ? 1.0
          : Math.min(1.0, (1.0 - cfg.current.smoothness) * 28.0 * dt);

      for (const prop in targetPose) {
        if (typeof targetPose[prop] === 'number') {
          cur[prop] = cur[prop] + (targetPose[prop] - cur[prop]) * alpha;
        } else {
          cur[prop] = targetPose[prop];
        }
      }
      return cur;
    }

    // ============================================================================
    // 1. CINEMATIC MONOCHROME SPOTLIGHT BEAMS & SUBTLE STAGE HAZE
    // ============================================================================
    function renderCinematicBackground(lightTime, stageRow) {
      if (cfg.current.spotlight <= 0.01) return;
      const aspect = getAspect();
      const t = lightTime;
      const intensity = cfg.current.spotlight;

      const mainTopC = grid.cols * 0.5;
      const mainBotC = grid.cols * (0.5 + Math.sin(t * 0.38) * 0.045);

      const leftTopC = grid.cols * 0.23;
      const leftBotC = grid.cols * (0.21 + Math.sin(t * 0.26 + 1.1) * 0.08);

      const rightTopC = grid.cols * 0.77;
      const rightBotC = grid.cols * (0.79 + Math.cos(t * 0.24 + 2.4) * 0.08);

      const maxFloorR = Math.floor(grid.rows * 0.96);

      for (let r = 2; r < maxFloorR; r++) {
        const rowNorm = r / grid.rows;
        const rowOff = r * grid.cols;

        const pMain = r / Math.max(1, stageRow);
        const cMain = mainTopC + (mainBotC - mainTopC) * pMain;
        const wMain = (3.0 + pMain * 14.0) / aspect;

        const pSide = r / Math.max(1, maxFloorR);
        const cLeft = leftTopC + (leftBotC - leftTopC) * pSide;
        const wLeft = (2.2 + pSide * 18.0) / aspect;

        const cRight = rightTopC + (rightBotC - rightTopC) * pSide;
        const wRight = (2.2 + pSide * 18.0) / aspect;

        const hazeWave = 0.78 + 0.22 * Math.sin(r * 0.11 - t * 0.5);

        for (let c = 0; c < grid.cols; c++) {
          let lum = 0;

          const dMain = Math.abs(c - cMain) / wMain;
          if (dMain < 1.0) {
            const g = Math.cos(dMain * Math.PI * 0.5);
            lum += g * g * (1.0 - rowNorm * 0.32) * 0.24 * hazeWave * intensity;
          }

          const dLeft = Math.abs(c - cLeft) / wLeft;
          if (dLeft < 1.0) {
            const g = Math.cos(dLeft * Math.PI * 0.5);
            lum += g * g * (1.0 - rowNorm * 0.42) * 0.15 * hazeWave * intensity;
          }

          const dRight = Math.abs(c - cRight) / wRight;
          if (dRight < 1.0) {
            const g = Math.cos(dRight * Math.PI * 0.5);
            lum += g * g * (1.0 - rowNorm * 0.42) * 0.15 * hazeWave * intensity;
          }

          if (lum > 0.04) {
            grid.lumBuf[rowOff + c] = Math.min(0.42, lum);
          }
        }
      }

      const stageLeftC = Math.floor(grid.cols * 0.36);
      const stageRightC = Math.floor(grid.cols * 0.64);
      if (stageRow >= 0 && stageRow < grid.rows) {
        const rowOff = stageRow * grid.cols;
        for (let c = stageLeftC; c <= stageRightC; c++) {
          const distNorm = Math.abs(c - grid.cols * 0.5) / (grid.cols * 0.14);
          const fade = Math.max(0, 1.0 - distNorm * distNorm);
          grid.lumBuf[rowOff + c] = Math.max(
            grid.lumBuf[rowOff + c],
            Math.min(0.65, fade * 0.42 * intensity),
          );
        }
      }
    }

    // ============================================================================
    // 2. ANATOMICALLY PROPORTIONED HUMAN SILHOUETTE & CHIAROSCURO SHADING
    // ============================================================================
    function drawAnatomicalSegment(ax, ay, bx, by, rA, rB, zVal, bodyId, lightSide, midBulge) {
      const aspect = getAspect();
      const maxR = Math.max(rA, rB) * (midBulge ? 1.16 : 1.0);
      const padX = Math.ceil(maxR / aspect) + 1;
      const padY = Math.ceil(maxR) + 1;

      const cMin = Math.max(0, Math.floor(Math.min(ax, bx) - padX));
      const cMax = Math.min(grid.cols - 1, Math.ceil(Math.max(ax, bx) + padX));
      const rMin = Math.max(0, Math.floor(Math.min(ay, by) - padY));
      const rMax = Math.min(grid.rows - 1, Math.ceil(Math.max(ay, by) + padY));

      const sx = (bx - ax) * aspect;
      const sy = by - ay;
      const lenSq = sx * sx + sy * sy;
      const len = Math.sqrt(lenSq);

      const perpX = len > 0.001 ? -sy / len : 1.0;
      const perpY = len > 0.001 ? sx / len : 0.0;
      const contrast = cfg.current.contrast;

      for (let r = rMin; r <= rMax; r++) {
        const py = r - ay;
        const rowOff = r * grid.cols;
        for (let c = cMin; c <= cMax; c++) {
          const px = (c - ax) * aspect;

          let t = 0;
          if (lenSq > 0.0001) {
            t = (px * sx + py * sy) / lenSq;
          }
          if (t < -0.06 || t > 1.06) continue;
          const tClamped = Math.max(0, Math.min(1, t));

          const dx = px - tClamped * sx;
          const dy = py - tClamped * sy;
          const dist = Math.sqrt(dx * dx + dy * dy);

          let rad = rA + (rB - rA) * tClamped;
          if (midBulge && tClamped > 0.12 && tClamped < 0.72) {
            const mPhase = (tClamped - 0.12) / 0.6;
            rad *= 1.0 + midBulge * Math.sin(mPhase * Math.PI);
          }

          if (dist <= rad) {
            const u = dist / Math.max(0.001, rad);
            const signedSide = (dx * perpX + dy * perpY) / Math.max(0.001, rad);

            const lightFactor = 0.52 + 0.48 * (signedSide * lightSide);
            const cylNz = Math.sqrt(Math.max(0, 1.0 - u * u));
            let lum = (0.18 + 0.82 * Math.pow(cylNz, 0.75) * lightFactor) * contrast;

            if (u > 0.8) {
              const edgeT = (1.0 - u) / 0.2;
              lum = Math.min(lum, (0.16 + 0.36 * edgeT) * contrast);
            }

            const idx = rowOff + c;
            if (grid.bodyIdBuf[idx] === bodyId && zVal > grid.zBuf[idx] + 0.4 && u > 0.72) {
              lum = 0.12;
            }

            if (zVal >= grid.zBuf[idx]) {
              grid.zBuf[idx] = zVal;
              grid.lumBuf[idx] = Math.min(1.0, Math.max(0.1, lum));
              grid.bodyIdBuf[idx] = bodyId;
            }
          }
        }
      }
    }

    function drawSculptedTorso(shoulderC, shoulderR, hipC, hipR, figH, build, zVal, bodyId, lightSide) {
      const aspect = getAspect();
      const topR = Math.floor(shoulderR);
      const botR = Math.ceil(hipR);
      const torsoH = Math.max(1, botR - topR);

      const shW = build.shWidth * cfg.current.shoulderWidth;
      const chW = build.chestWidth * cfg.current.shoulderWidth;
      const waW = build.waistWidth * cfg.current.waistWidth;
      const hiW = build.hipWidth * cfg.current.hipWidth;
      const contrast = cfg.current.contrast;

      for (let r = topR; r <= botR; r++) {
        if (r < 0 || r >= grid.rows) continue;
        const t = (r - topR) / torsoH;
        const spineC =
          shoulderC + (hipC - shoulderC) * t + Math.sin(t * Math.PI) * (hipC - shoulderC) * 0.15;

        let halfW = chW;
        if (t < 0.11) {
          const u = t / 0.11;
          halfW = (0.028 * cfg.current.headScale + (shW - 0.028 * cfg.current.headScale) * Math.pow(u, 0.65)) * figH;
        } else if (t < 0.58) {
          const u = (t - 0.11) / 0.47;
          const sCurve = u * u * (3 - 2 * u);
          halfW = (chW * (1 - sCurve) + waW * sCurve) * figH;
        } else if (t < 0.88) {
          const u = (t - 0.58) / 0.3;
          const sCurve = u * u * (3 - 2 * u);
          halfW = (waW * (1 - sCurve) + hiW * sCurve) * figH;
        } else {
          const u = (t - 0.88) / 0.12;
          halfW = hiW * (1 - u * 0.14) * figH;
        }

        const halfCols = halfW / aspect;
        const cStart = Math.max(0, Math.floor(spineC - halfCols - 1));
        const cEnd = Math.min(grid.cols - 1, Math.ceil(spineC + halfCols + 1));
        const rowOff = r * grid.cols;

        for (let c = cStart; c <= cEnd; c++) {
          const dx = (c - spineC) * aspect;
          const absDx = Math.abs(dx);
          if (absDx > halfW) continue;

          if (t > 0.89 && absDx < 0.015 * figH) continue;

          const u = absDx / Math.max(0.001, halfW);
          const signedX = dx / Math.max(0.001, halfW);

          const nz = Math.sqrt(Math.max(0, 1.0 - u * u));
          const light = 0.48 + 0.52 * (signedX * lightSide);
          const centerCrease = absDx < 0.012 * figH && t > 0.15 && t < 0.65 ? 0.86 : 1.0;
          const waistCrease = t > 0.5 && t < 0.66 ? 0.88 : 1.0;

          let lum = (0.18 + 0.82 * Math.pow(nz, 0.75) * light) * centerCrease * waistCrease * contrast;
          if (u > 0.82) {
            lum = Math.min(lum, (0.16 + 0.34 * ((1.0 - u) / 0.18)) * contrast);
          }

          const idx = rowOff + c;
          if (zVal >= grid.zBuf[idx]) {
            grid.zBuf[idx] = zVal;
            grid.lumBuf[idx] = Math.min(1.0, Math.max(0.1, lum));
            grid.bodyIdBuf[idx] = bodyId;
          }
        }
      }
    }

    function drawAnatomicalHeadAndNeck(neckBaseC, neckBaseR, headTiltX, figH, headStyle, zVal, bodyId, lightSide) {
      const aspect = getAspect();
      const hs = cfg.current.headScale;
      const contrast = cfg.current.contrast;

      const neckTopC = neckBaseC + (headTiltX * 0.3 * figH) / aspect;
      const neckTopR = neckBaseR - 0.042 * figH * hs;
      drawAnatomicalSegment(
        neckBaseC,
        neckBaseR + 0.008 * figH,
        neckTopC,
        neckTopR,
        0.021 * figH * hs,
        0.019 * figH * hs,
        zVal,
        bodyId,
        lightSide,
        0,
      );

      const headBotR = neckTopR + 0.005 * figH;
      const headTopR = headBotR - 0.104 * figH * hs;
      const headCenterC = neckTopC + (headTiltX * 0.4 * figH) / aspect;

      const rStart = Math.max(0, Math.floor(headTopR - 1));
      const rEnd = Math.min(grid.rows - 1, Math.ceil(headBotR + 1));
      const hSpan = Math.max(1, headBotR - headTopR);

      for (let r = rStart; r <= rEnd; r++) {
        const t = (r - headTopR) / hSpan;
        if (t < 0 || t > 1) continue;

        let halfW = 0.039 * figH * hs;
        if (t < 0.22) {
          halfW = (0.022 + (0.042 - 0.022) * Math.sin((t / 0.22) * Math.PI * 0.5)) * figH * hs;
        } else if (t < 0.65) {
          halfW = (0.042 - (t - 0.22) * 0.011) * figH * hs;
        } else {
          const jawU = (t - 0.65) / 0.35;
          halfW = 0.037 * (1.0 - jawU * 0.6) * figH * hs;
        }

        if (headStyle === 1 && t < 0.38) {
          halfW *= 1.1;
        } else if (headStyle === 2 && t > 0.15 && t < 0.52) {
          halfW *= 1.07;
        }

        const halfCols = halfW / aspect;
        const cMin = Math.max(0, Math.floor(headCenterC - halfCols - 1));
        const cMax = Math.min(grid.cols - 1, Math.ceil(headCenterC + halfCols + 1));
        const rowOff = r * grid.cols;

        for (let c = cMin; c <= cMax; c++) {
          const dx = (c - headCenterC) * aspect;
          const absDx = Math.abs(dx);
          if (absDx > halfW) continue;

          const u = absDx / Math.max(0.001, halfW);
          const signedX = dx / Math.max(0.001, halfW);
          const nz = Math.sqrt(Math.max(0, 1.0 - u * u));
          const light = 0.48 + 0.52 * (signedX * lightSide);

          let lum = (0.22 + 0.78 * Math.pow(nz, 0.75) * light) * contrast;
          if (u > 0.78) {
            lum = Math.min(lum, (0.18 + 0.34 * ((1.0 - u) / 0.22)) * contrast);
          }

          const idx = rowOff + c;
          if (zVal + 0.6 >= grid.zBuf[idx]) {
            grid.zBuf[idx] = zVal + 0.6;
            grid.lumBuf[idx] = Math.min(1.0, lum);
            grid.bodyIdBuf[idx] = bodyId;
          }
        }
      }
    }

    function drawHandWithFingers(elbowC, elbowR, wristC, wristR, figH, zVal, bodyId, lightSide, spreadFingers) {
      const aspect = getAspect();
      const lt = cfg.current.limbThick;
      const dx = (wristC - elbowC) * aspect;
      const dy = wristR - elbowR;
      const len = Math.max(0.001, Math.hypot(dx, dy));
      const ux = dx / len;
      const uy = dy / len;
      const px = -uy;
      const py = ux;

      const palmLen = 0.023 * figH;
      const palmEndC = wristC + (ux * palmLen) / aspect;
      const palmEndR = wristR + uy * palmLen;
      drawAnatomicalSegment(
        wristC,
        wristR,
        palmEndC,
        palmEndR,
        0.014 * figH * lt,
        0.016 * figH * lt,
        zVal,
        bodyId,
        lightSide,
        0,
      );

      if (spreadFingers && cfg.current.fingers) {
        const fingerLen = 0.02 * figH;
        const angles = [-0.32, 0.0, 0.32];
        for (let i = 0; i < angles.length; i++) {
          const a = angles[i];
          const cosA = Math.cos(a);
          const sinA = Math.sin(a);
          const fx = ux * cosA - uy * sinA;
          const fy = ux * sinA + uy * cosA;
          const tipC = palmEndC + (fx * fingerLen) / aspect;
          const tipR = palmEndR + fy * fingerLen;
          drawAnatomicalSegment(
            palmEndC + (px * (i - 1) * 0.004 * figH) / aspect,
            palmEndR + py * (i - 1) * 0.004 * figH,
            tipC,
            tipR,
            0.008 * figH * lt,
            0.005 * figH * lt,
            zVal + 0.2,
            bodyId,
            lightSide,
            0,
          );
        }
      }
    }

    function renderHuman(rootC, footFloorR, figH, build, pose, zBase, bodyId, lightSide, isSinger) {
      const aspect = getAspect();

      const jumpOffsetR = (pose.jumpOffset || 0) * figH;
      const hipSinkR = (pose.hipSink || 0) * figH;

      const hipCenterC = rootC + (pose.hipSwayX * figH) / aspect;
      const hipCenterR = footFloorR - 0.48 * figH + jumpOffsetR + hipSinkR;

      const shoulderCenterC = rootC + (pose.shoulderSwayX * figH) / aspect;
      const shoulderCenterR = footFloorR - 0.82 * figH + jumpOffsetR + hipSinkR * 0.85;

      // 1. Torso
      drawSculptedTorso(
        shoulderCenterC,
        shoulderCenterR,
        hipCenterC,
        hipCenterR,
        figH,
        build,
        zBase,
        bodyId,
        lightSide,
      );

      // 2. Neck & Head
      drawAnatomicalHeadAndNeck(
        shoulderCenterC,
        shoulderCenterR,
        pose.headTiltX,
        figH,
        build.headStyle || 0,
        zBase + 0.5,
        bodyId,
        lightSide,
      );

      // 3. Legs
      const hipSocketSpan = 0.045 * figH * cfg.current.hipWidth;
      const hipLC = hipCenterC - hipSocketSpan / aspect;
      const hipRC = hipCenterC + hipSocketSpan / aspect;
      const hipJointR = hipCenterR - 0.01 * figH;

      const footLC = rootC + (pose.footLX * figH * cfg.current.hipWidth) / aspect;
      const footLR = footFloorR + jumpOffsetR - (pose.liftL || 0) * figH;

      const footRC = rootC + (pose.footRX * figH * cfg.current.hipWidth) / aspect;
      const footRR = footFloorR + jumpOffsetR - (pose.liftR || 0) * figH;

      const kneeLC = (hipLC + footLC) * 0.5 + (pose.kneeBendLX * figH) / aspect;
      const kneeLR = (hipJointR + footLR) * 0.52;

      const kneeRC = (hipRC + footRC) * 0.5 + (pose.kneeBendRX * figH) / aspect;
      const kneeRR = (hipJointR + footRR) * 0.52;

      const lt = build.limbThick * cfg.current.limbThick;

      drawAnatomicalSegment(hipLC, hipJointR, kneeLC, kneeLR, 0.034 * figH * lt, 0.022 * figH * lt, zBase + 0.2, bodyId, lightSide, 0.06);
      drawAnatomicalSegment(kneeLC, kneeLR, footLC, footLR - 0.015 * figH, 0.021 * figH * lt, 0.013 * figH * lt, zBase + 0.3, bodyId, lightSide, 0.16);
      drawAnatomicalSegment(
        footLC + (0.01 * figH) / aspect,
        footLR - 0.01 * figH,
        footLC - (0.034 * figH) / aspect,
        footLR,
        0.017 * figH * lt,
        0.013 * figH * lt,
        zBase + 0.4,
        bodyId,
        0,
      );

      drawAnatomicalSegment(hipRC, hipJointR, kneeRC, kneeRR, 0.034 * figH * lt, 0.022 * figH * lt, zBase + 0.2, bodyId, lightSide, 0.06);
      drawAnatomicalSegment(kneeRC, kneeRR, footRC, footRR - 0.015 * figH, 0.021 * figH * lt, 0.013 * figH * lt, zBase + 0.3, bodyId, lightSide, 0.16);
      drawAnatomicalSegment(
        footRC - (0.01 * figH) / aspect,
        footRR - 0.01 * figH,
        footRC + (0.034 * figH) / aspect,
        footRR,
        0.017 * figH * lt,
        0.013 * figH * lt,
        zBase + 0.4,
        bodyId,
        0,
      );

      // 4. Arms via Fixed-Length Forward Kinematics
      const shSpan = build.shWidth * cfg.current.shoulderWidth * figH;
      const shLC = shoulderCenterC - shSpan / aspect;
      const shRC = shoulderCenterC + shSpan / aspect;
      const shJointR = shoulderCenterR + 0.022 * figH;

      const upperArmLen = 0.138 * figH * cfg.current.armLength;
      const forearmLen = 0.122 * figH * cfg.current.armLength;

      const elbLC = shLC - (Math.sin(pose.shAngleL) * upperArmLen) / aspect;
      const elbLR = shJointR + Math.cos(pose.shAngleL) * upperArmLen;
      const wristLC = elbLC - (Math.sin(pose.elbAngleL) * forearmLen) / aspect;
      const wristLR = elbLR + Math.cos(pose.elbAngleL) * forearmLen;

      let elbRC;
      let elbRR;
      let wristRC;
      let wristRR;
      const headC = shoulderCenterC + (pose.headTiltX * 0.4 * figH) / aspect;
      const headR = shoulderCenterR - 0.09 * figH * cfg.current.headScale;

      if (isSinger) {
        elbRC = shRC + (0.048 * figH * cfg.current.armLength) / aspect;
        elbRR = shJointR + 0.068 * figH * cfg.current.armLength;
        wristRC = headC + (0.044 * figH) / aspect;
        wristRR = headR + 0.042 * figH;
      } else {
        elbRC = shRC + (Math.sin(pose.shAngleR) * upperArmLen) / aspect;
        elbRR = shJointR + Math.cos(pose.shAngleR) * upperArmLen;
        wristRC = elbRC + (Math.sin(pose.elbAngleR) * forearmLen) / aspect;
        wristRR = elbRR + Math.cos(pose.elbAngleR) * forearmLen;
      }

      drawAnatomicalSegment(shLC, shJointR, elbLC, elbLR, 0.024 * figH * lt, 0.018 * figH * lt, zBase + 1.0, bodyId, lightSide, 0.07);
      drawAnatomicalSegment(elbLC, elbLR, wristLC, wristLR, 0.018 * figH * lt, 0.013 * figH * lt, zBase + 1.2, bodyId, lightSide, 0.09);
      drawHandWithFingers(elbLC, elbLR, wristLC, wristLR, figH, zBase + 1.3, bodyId, lightSide, pose.spreadL !== false);

      drawAnatomicalSegment(shRC, shJointR, elbRC, elbRR, 0.024 * figH * lt, 0.018 * figH * lt, zBase + 1.0, bodyId, lightSide, 0.07);
      drawAnatomicalSegment(elbRC, elbRR, wristRC, wristRR, 0.018 * figH * lt, 0.013 * figH * lt, zBase + 1.2, bodyId, lightSide, 0.09);
      drawHandWithFingers(elbRC, elbRR, wristRC, wristRR, figH, zBase + 1.3, bodyId, lightSide, !isSinger && pose.spreadR !== false);

      return {
        headC,
        headR,
        wristRC,
        wristRR,
        wristLC,
        wristLR,
      };
    }

    // ============================================================================
    // 3. DISTINCT INDIVIDUAL DANCE POSTURES & NATURAL BIOMECHANICAL MOTION
    // ============================================================================
    function evaluateDancerTargetPose(d, animTime) {
      const t = animTime * 2.4 * d.tempoMul + d.phase;
      const sin1 = Math.sin(t);
      const cos1 = Math.cos(t);
      const sinHalf = Math.sin(t * 0.5);
      const cosHalf = Math.cos(t * 0.5);

      const bMul = cfg.current.bounce;
      const sMul = cfg.current.sway;
      const aMul = cfg.current.armSwing;
      const jMul = cfg.current.jumpHeight;

      const groovePulse = Math.pow(Math.max(0, sin1), 2) * bMul;

      const phraseWave = Math.sin(t * 0.25);
      const isJumping = jMul > 0.02 && (d.style === 1 || d.style === 6) && phraseWave > 0.78;
      const jumpHeight = isJumping ? -Math.max(0, sin1) * 0.064 * jMul : 0;
      const kneeSink = isJumping ? Math.max(0, -sin1) * 0.03 * bMul : groovePulse * 0.024;

      switch (d.style % 8) {
        case 0:
          return {
            jumpOffset: jumpHeight,
            hipSink: groovePulse * 0.022,
            hipSwayX: sinHalf * 0.032 * sMul,
            shoulderSwayX: -sinHalf * 0.02 * sMul,
            headTiltX: sin1 * 0.022 * sMul,
            shAngleL: 0.42,
            elbAngleL: -0.52,
            shAngleR: 0.34,
            elbAngleR: 2.15 + sin1 * 0.28 * aMul,
            spreadL: false,
            spreadR: true,
            footLX: -0.062,
            footRX: 0.062,
            liftL: Math.max(0, sinHalf) * 0.02 * bMul,
            liftR: Math.max(0, -sinHalf) * 0.02 * bMul,
            kneeBendLX: -0.02 + sinHalf * 0.02 * sMul,
            kneeBendRX: 0.02 + sinHalf * 0.02 * sMul,
          };

        case 1:
          return {
            jumpOffset: jumpHeight,
            hipSink: kneeSink,
            hipSwayX: cosHalf * 0.034 * sMul,
            shoulderSwayX: -cosHalf * 0.022 * sMul,
            headTiltX: (0.02 + sinHalf * 0.018) * sMul,
            shAngleL: 0.22 + Math.abs(sinHalf) * 0.08 * aMul,
            elbAngleL: 0.45 + sin1 * 0.15 * aMul,
            shAngleR: 2.62 + sinHalf * 0.14 * aMul,
            elbAngleR: 3.02 + sin1 * 0.18 * aMul,
            spreadL: false,
            spreadR: true,
            footLX: -0.066,
            footRX: 0.066,
            liftL: !isJumping && sin1 > 0.3 ? (sin1 - 0.3) * 0.024 * bMul : 0,
            liftR: !isJumping && sin1 < -0.3 ? (-sin1 - 0.3) * 0.024 * bMul : 0,
            kneeBendLX: -0.022 + cosHalf * 0.02 * sMul,
            kneeBendRX: 0.022 + cosHalf * 0.02 * sMul,
          };

        case 2:
          return {
            jumpOffset: 0,
            hipSink: Math.abs(sin1) * 0.024 * bMul,
            hipSwayX: sinHalf * 0.038 * sMul,
            shoulderSwayX: sinHalf * 0.022 * sMul,
            headTiltX: -sinHalf * 0.024 * sMul,
            shAngleL: 0.46,
            elbAngleL: -2.25 + sin1 * 0.22 * aMul,
            shAngleR: 0.46,
            elbAngleR: -2.25 - sin1 * 0.22 * aMul,
            spreadL: false,
            spreadR: false,
            footLX: -0.06 + Math.max(0, sinHalf) * 0.022 * sMul,
            footRX: 0.06 + Math.min(0, sinHalf) * 0.022 * sMul,
            liftL: Math.max(0, sinHalf) * 0.022 * bMul,
            liftR: Math.max(0, -sinHalf) * 0.022 * bMul,
            kneeBendLX: -0.02 + sinHalf * 0.018 * sMul,
            kneeBendRX: 0.02 + sinHalf * 0.018 * sMul,
          };

        case 3:
          return {
            jumpOffset: 0,
            hipSink: groovePulse * 0.026,
            hipSwayX: -sinHalf * 0.032 * sMul,
            shoulderSwayX: sinHalf * 0.02 * sMul,
            headTiltX: 0.024 * sMul,
            shAngleL: 2.65 + cosHalf * 0.14 * aMul,
            elbAngleL: 3.05 + cos1 * 0.16 * aMul,
            shAngleR: 0.48,
            elbAngleR: -0.6,
            spreadL: true,
            spreadR: false,
            footLX: -0.064,
            footRX: 0.064,
            liftL: Math.max(0, cos1) * 0.02 * bMul,
            liftR: Math.max(0, -cos1) * 0.02 * bMul,
            kneeBendLX: -0.022 - sinHalf * 0.018 * sMul,
            kneeBendRX: 0.022 - sinHalf * 0.018 * sMul,
          };

        case 4:
          return {
            jumpOffset: 0,
            hipSink: groovePulse * 0.025,
            hipSwayX: sinHalf * 0.034 * sMul,
            shoulderSwayX: -sinHalf * 0.02 * sMul,
            headTiltX: (-0.022 + sin1 * 0.015) * sMul,
            shAngleL: 0.25,
            elbAngleL: 2.2 + sin1 * 0.25 * aMul,
            shAngleR: 0.2,
            elbAngleR: 0.38,
            spreadL: true,
            spreadR: false,
            footLX: -0.062,
            footRX: 0.062,
            liftL: Math.max(0, sin1) * 0.02 * bMul,
            liftR: Math.max(0, -sin1) * 0.02 * bMul,
            kneeBendLX: -0.02 + sinHalf * 0.018 * sMul,
            kneeBendRX: 0.02 + sinHalf * 0.018 * sMul,
          };

        case 5: {
          const sway = sinHalf * 0.14 * aMul;
          return {
            jumpOffset: 0,
            hipSink: groovePulse * 0.026,
            hipSwayX: cosHalf * 0.035 * sMul,
            shoulderSwayX: sinHalf * 0.024 * sMul,
            headTiltX: sway * 0.15,
            shAngleL: 2.6 - sway,
            elbAngleL: 3.04 - sway,
            shAngleR: 2.6 + sway,
            elbAngleR: 3.04 + sway,
            spreadL: true,
            spreadR: true,
            footLX: -0.064,
            footRX: 0.064,
            liftL: Math.max(0, sin1) * 0.018 * bMul,
            liftR: Math.max(0, -sin1) * 0.018 * bMul,
            kneeBendLX: -0.022 + cosHalf * 0.018 * sMul,
            kneeBendRX: 0.022 + cosHalf * 0.018 * sMul,
          };
        }

        case 6:
          return {
            jumpOffset: jumpHeight,
            hipSink: kneeSink,
            hipSwayX: -cosHalf * 0.034 * sMul,
            shoulderSwayX: cosHalf * 0.022 * sMul,
            headTiltX: -0.02 * sMul,
            shAngleL: 0.48,
            elbAngleL: -0.58,
            shAngleR: 2.6 + sinHalf * 0.15 * aMul,
            elbAngleR: 3.0 + sin1 * 0.18 * aMul,
            spreadL: false,
            spreadR: true,
            footLX: -0.066,
            footRX: 0.066,
            liftL: !isJumping ? Math.max(0, -sin1) * 0.022 * bMul : 0,
            liftR: !isJumping ? Math.max(0, sin1) * 0.022 * bMul : 0,
            kneeBendLX: -0.024 - cosHalf * 0.018 * sMul,
            kneeBendRX: 0.024 - cosHalf * 0.018 * sMul,
          };

        default:
          return {
            jumpOffset: 0,
            hipSink: Math.abs(cos1) * 0.022 * bMul,
            hipSwayX: sinHalf * 0.032 * sMul,
            shoulderSwayX: sinHalf * 0.018 * sMul,
            headTiltX: cos1 * 0.024 * sMul,
            shAngleL: 0.34,
            elbAngleL: 2.1 + cos1 * 0.26 * aMul,
            shAngleR: 0.24,
            elbAngleR: 0.52 + sin1 * 0.15 * aMul,
            spreadL: true,
            spreadR: false,
            footLX: -0.062,
            footRX: 0.062,
            liftL: Math.max(0, cosHalf) * 0.02 * bMul,
            liftR: Math.max(0, -cosHalf) * 0.02 * bMul,
            kneeBendLX: -0.02 + sinHalf * 0.018 * sMul,
            kneeBendRX: 0.02 + sinHalf * 0.018 * sMul,
          };
      }
    }

    function evaluateSingerTargetPose(animTime) {
      const t = animTime * 2.2;
      const sin1 = Math.sin(t);
      const sinHalf = Math.sin(t * 0.5);
      const phrase = 0.5 + 0.5 * Math.sin(t * 0.24);

      const bMul = cfg.current.bounce;
      const sMul = cfg.current.sway;
      const aMul = cfg.current.armSwing;

      return {
        stageShiftX: Math.sin(t * 0.16) * 0.016 * sMul,
        pose: {
          jumpOffset: 0,
          hipSink: Math.pow(Math.max(0, sin1), 2) * 0.018 * bMul,
          hipSwayX: sinHalf * 0.022 * sMul,
          shoulderSwayX: sinHalf * 0.015 * sMul,
          headTiltX: (0.02 + sinHalf * 0.008) * sMul,
          shAngleL: 0.65 + phrase * 1.75 * aMul,
          elbAngleL: 2.15 + phrase * 0.75 * aMul + sin1 * 0.14 * aMul,
          shAngleR: 0.45,
          elbAngleR: -2.4,
          spreadL: true,
          spreadR: false,
          footLX: -0.064,
          footRX: 0.066,
          liftL: 0,
          liftR: Math.max(0, sin1) * 0.015 * bMul,
          kneeBendLX: -0.018,
          kneeBendRX: 0.022 + Math.max(0, sin1) * 0.012 * bMul,
        },
      };
    }

    // ============================================================================
    // 4. MAIN ANIMATION LOOP (With Accumulated Phase & Temporal Pose Smoothing)
    // ============================================================================
    const singerBuild = {
      shWidth: 0.11,
      chestWidth: 0.08,
      waistWidth: 0.055,
      hipWidth: 0.074,
      limbThick: 1.0,
      headStyle: 1,
    };

    let rafId = 0;

    function renderScene(nowMs) {
      const clock = clockRef.current;
      const dt =
        clock.lastFrameMs === 0
          ? 0.016
          : Math.min(0.05, Math.max(0.001, (nowMs - clock.lastFrameMs) * 0.001));
      clock.lastFrameMs = nowMs;

      clock.animClock += dt * cfg.current.speed;
      clock.lightClock += dt * cfg.current.lightSpeed;

      grid.lumBuf.fill(0);
      grid.bodyIdBuf.fill(0);
      grid.zBuf.fill(-9999);

      const stageFloorR = Math.floor(grid.rows * cfg.current.stageHeight);
      const singerFigH = Math.max(24, Math.floor(grid.rows * 0.36 * cfg.current.bodyScale * cfg.current.singerScale));

      // 1. Render Cinematic Monochrome Background Spotlights & Haze
      renderCinematicBackground(clock.lightClock, stageFloorR);

      // 2. Render Lead Singer on Center Stage
      const singerTarget = evaluateSingerTargetPose(clock.animClock);
      const singerPose = smoothPoseState('singer', singerTarget.pose, dt);
      const singerRootC = grid.cols * (0.5 + singerTarget.stageShiftX);

      const singerAnchors = renderHuman(
        singerRootC,
        stageFloorR,
        singerFigH,
        singerBuild,
        singerPose,
        10,
        1,
        0.7,
        true,
      );

      // Coherent Microphone & Angled Stand Held Directly at Singer's Mouth
      const aspect = getAspect();
      const micHandC = singerAnchors.wristRC;
      const micHandR = singerAnchors.wristRR;
      const micTipC = singerAnchors.headC + (0.024 * singerFigH) / aspect;
      const micTipR = singerAnchors.headR + 0.022 * singerFigH;

      drawAnatomicalSegment(
        micTipC,
        micTipR,
        micHandC + (0.012 * singerFigH) / aspect,
        micHandR + 0.01 * singerFigH,
        0.015 * singerFigH,
        0.01 * singerFigH,
        12.0,
        99,
        0.85,
        0,
      );
      const standFootC = micHandC + (0.045 * singerFigH) / aspect;
      drawAnatomicalSegment(
        micHandC,
        micHandR,
        standFootC,
        stageFloorR,
        0.007 * singerFigH,
        0.008 * singerFigH,
        11.8,
        99,
        0.85,
        0,
      );
      drawAnatomicalSegment(
        standFootC - (0.026 * singerFigH) / aspect,
        stageFloorR,
        standFootC + (0.026 * singerFigH) / aspect,
        stageFloorR,
        0.009 * singerFigH,
        0.009 * singerFigH,
        11.8,
        99,
        0.85,
        0,
      );

      // 3. Render the Dancers on the Floor
      for (let i = 0; i < crowd.length; i++) {
        const d = crowd[i];
        const dRootC = d.xNorm * grid.cols;
        const dFootR = Math.floor(d.footY * grid.rows);
        const dFigH = Math.max(22, Math.floor(grid.rows * d.scale * cfg.current.bodyScale));
        const targetPose = evaluateDancerTargetPose(d, clock.animClock);
        const dPose = smoothPoseState(`dancer_${d.id}`, targetPose, dt);
        const lightSide = d.xNorm < 0.5 ? 0.75 : -0.75;

        renderHuman(dRootC, dFootR, dFigH, d, dPose, d.zBase, d.id, lightSide, false);
      }

      // 4. Batched Monochrome Terminal Output onto Canvas
      const w = window.innerWidth;
      const h = window.innerHeight;
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, w, h);

      const lpx = cfg.current.linePx;
      ctx.font = `600 ${lpx}px "JetBrains Mono", monospace`;
      ctx.textBaseline = 'top';
      ctx.textAlign = 'left';

      const activeRamp = RAMPS[cfg.current.rampKey] || RAMPS.classic;
      const rampMax = activeRamp.length - 1;
      const shadowCut = Math.floor(rampMax * 0.36);
      const midCut = Math.floor(rampMax * 0.68);

      for (let r = 0; r < grid.rows; r++) {
        const rowOff = r * grid.cols;
        let hasBg = false;
        let hasShadow = false;
        let hasMid = false;
        let hasHigh = false;

        let bgStr = '';
        let shadowStr = '';
        let midStr = '';
        let highStr = '';

        for (let c = 0; c < grid.cols; c++) {
          const lum = grid.lumBuf[rowOff + c];
          if (lum <= 0.04) {
            bgStr += ' ';
            shadowStr += ' ';
            midStr += ' ';
            highStr += ' ';
          } else {
            const charIdx = Math.min(rampMax, Math.max(1, Math.round(lum * rampMax)));
            const ch = activeRamp[charIdx];
            const isPerson = grid.bodyIdBuf[rowOff + c] > 0;

            if (!isPerson) {
              bgStr += ch;
              shadowStr += ' ';
              midStr += ' ';
              highStr += ' ';
              hasBg = true;
            } else if (charIdx <= shadowCut) {
              shadowStr += ch;
              bgStr += ' ';
              midStr += ' ';
              highStr += ' ';
              hasShadow = true;
            } else if (charIdx <= midCut) {
              midStr += ch;
              bgStr += ' ';
              shadowStr += ' ';
              highStr += ' ';
              hasMid = true;
            } else {
              highStr += ch;
              bgStr += ' ';
              shadowStr += ' ';
              midStr += ' ';
              hasHigh = true;
            }
          }
        }

        const y = r * lpx;
        if (hasBg) {
          ctx.fillStyle = '#404040';
          ctx.fillText(bgStr, 0, y);
        }
        if (hasShadow) {
          ctx.fillStyle = '#737373';
          ctx.fillText(shadowStr, 0, y);
        }
        if (hasMid) {
          ctx.fillStyle = '#c4c4c4';
          ctx.fillText(midStr, 0, y);
        }
        if (hasHigh) {
          ctx.fillStyle = '#ffffff';
          ctx.fillText(highStr, 0, y);
        }
      }

      rafId = requestAnimationFrame(renderScene);
    }

    buildCrowd();
    resizeCanvas();

    const onResize = () => resizeCanvas();
    window.addEventListener('resize', onResize);
    document.body.classList.add('cd-intro-open');

    controlsRef.current.rebuildCrowd = buildCrowd;
    controlsRef.current.resizeCanvas = resizeCanvas;

    rafId = requestAnimationFrame(renderScene);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', onResize);
      document.body.classList.remove('cd-intro-open');
      controlsRef.current.rebuildCrowd = null;
      controlsRef.current.resizeCanvas = null;
      smoothedPosesRef.current = {};
      crowdRef.current = [];
    };
  }, []);

  useEffect(
    () => () => {
      if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
    },
    [],
  );

  const handleSlider = (binding) => (event) => {
    const num = parseFloat(event.target.value);
    cfg.current[binding.key] = num;
    setValues((prev) => ({ ...prev, [binding.key]: binding.fmt(num) }));
    if (binding.rebuildCrowd) controlsRef.current.rebuildCrowd?.();
    if (binding.resize) controlsRef.current.resizeCanvas?.();
  };

  const handleFingers = (event) => {
    cfg.current.fingers = event.target.checked;
    setFingersOn(event.target.checked);
  };

  const handleRamp = (event) => {
    cfg.current.rampKey = event.target.value;
    setRampKey(event.target.value);
  };

  const handleReset = () => {
    cfg.current = { ...DEFAULTS };
    setValues(defaultLabels());
    setFingersOn(DEFAULTS.fingers);
    setRampKey(DEFAULTS.rampKey);
    controlsRef.current.rebuildCrowd?.();
    controlsRef.current.resizeCanvas?.();
    setStatus('Reset to defaults ✓');
  };

  const handleCopy = async () => {
    const json = JSON.stringify(cfg.current, null, 2);
    try {
      await navigator.clipboard.writeText(json);
      setStatus('Settings copied to clipboard ✓');
    } catch {
      // Clipboard API can be unavailable outside secure contexts.
      const ta = document.createElement('textarea');
      ta.value = json;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        setStatus('Settings copied to clipboard ✓');
      } catch {
        setStatus('Copy ready');
      }
      document.body.removeChild(ta);
    }
  };

  const handleGetStarted = () => {
    if (leavingRef.current) return;
    leavingRef.current = true;
    setLeaving(true);
    leaveTimerRef.current = window.setTimeout(onGetStarted, 420);
  };

  const renderGroup = (group, title) => (
    <div className="cd-section">
      <div className="cd-section-title">{title}</div>
      {group.map((key) => {
        const binding = BINDING_BY_KEY[key];
        return (
          <div key={binding.key}>
            <div className="cd-ctrl-row">
              <label className="cd-ctrl-label" htmlFor={`cd-${binding.key}`}>
                {binding.label}
              </label>
              <span className="cd-ctrl-value">{values[binding.key]}</span>
            </div>
            <input
              id={`cd-${binding.key}`}
              className="cd-range"
              type="range"
              min={binding.min}
              max={binding.max}
              step={binding.step}
              value={cfg.current[binding.key]}
              onChange={handleSlider(binding)}
            />
          </div>
        );
      })}
    </div>
  );

  return (
    <div className={`cd-intro${leaving ? ' cd-leaving' : ''}`}>
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="cd-brand">
        <div className="cd-brand-name" aria-label="ClashDoctor">
          CLASHDOCTOR
        </div>
        <button type="button" className="cd-cta" onClick={handleGetStarted}>
          Get Started
        </button>
      </div>
      <div className="cd-tune-toggle">
        <button type="button" className="cd-tune-btn" onClick={() => setDrawerOpen((open) => !open)}>
          [ ⚙ Tune Attributes ]
        </button>
      </div>
      <aside className={`cd-drawer${drawerOpen ? '' : ' cd-hidden'}`} aria-label="Studio attribute tuner">
        <div className="cd-drawer-head">
          <div>
            <div className="cd-drawer-title">Studio Attribute Tuner</div>
            <div className="cd-drawer-sub">Adjust live to lock in final parameters</div>
          </div>
          <div className="cd-head-actions">
            <button
              type="button"
              className="cd-mini-btn"
              onClick={handleReset}
              title="Reset all sliders to default"
            >
              Reset
            </button>
            <button
              type="button"
              className="cd-mini-btn"
              onClick={() => setDrawerOpen(false)}
              title="Hide panel to inspect full screen"
            >
              Hide
            </button>
          </div>
        </div>
        <div className="cd-drawer-scroll">
          {renderGroup(GROUP_01, '01 // Smoothness & Speed')}
          <div className="cd-section">
            <div className="cd-section-title">02 // Human Body Anatomy</div>
            {renderGroup(GROUP_02)}
            <div className="cd-ctrl-static">
              <label className="cd-ctrl-label" htmlFor="cd-fingers">
                Articulated Hand Fingers
              </label>
              <input
                id="cd-fingers"
                className="cd-check"
                type="checkbox"
                checked={fingersOn}
                onChange={handleFingers}
              />
            </div>
          </div>
          {renderGroup(GROUP_03, '03 // Crowd & Stage Layout')}
          <div className="cd-section">
            <div className="cd-section-title">04 // ASCII & Lighting</div>
            {renderGroup(GROUP_04)}
            <div>
              <div className="cd-ctrl-row">
                <label className="cd-ctrl-label" htmlFor="cd-ramp">
                  Character Ramp
                </label>
              </div>
              <select id="cd-ramp" className="cd-select" value={rampKey} onChange={handleRamp}>
                {RAMP_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="cd-drawer-foot">
          <span className="cd-status">{status}</span>
          <button type="button" className="cd-copy-btn" onClick={handleCopy}>
            Copy Settings
          </button>
        </div>
      </aside>
    </div>
  );
}
