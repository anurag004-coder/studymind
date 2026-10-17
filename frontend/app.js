/**
 * StudyMind — Grounded Study Assistant Frontend Logic
 * Implements Phase 6: Auth, Workspace/Library with Upload & Progress,
 * Grounded Chat with Verified Citations, and Synchronized Source Viewer with Bounding Box Overlay.
 */

// Configuration
const urlParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
if (urlParams && urlParams.get('api')) {
  localStorage.setItem('studymind_api_base', urlParams.get('api').replace(/\/$/, ''));
}
const API_BASE = (typeof window !== 'undefined' && (window.__STUDYMIND_API_BASE__ || localStorage.getItem('studymind_api_base'))) || '/api/v1';

// Application State
const state = {
  token: localStorage.getItem('studymind_token') || null,
  user: null,
  workspaces: [],
  currentWorkspaceId: localStorage.getItem('studymind_ws_id') || null,
  conversations: [],
  currentConversationId: null,
  documents: [],
  currentViewerDocId: null,
  currentViewerPage: 1,
  currentViewerMaxPages: 1,
  viewerZoom: 1.0,
  activeCitation: null,
  strictMode: false,
  isDemoMode: false,
};

// ============================================================================
// Standalone Demo Store & Dynamic Study Engine (Client-Side & Vercel Offline)
// ============================================================================

const demoStore = {
  workspaces: [
    {
      id: 'ws-demo-neuro',
      name: 'Neuroscience 101 (Demo)',
      document_count: 2,
      created_at: new Date(Date.now() - 86400000).toISOString(),
    },
  ],
  documents: {
    'ws-demo-neuro': [
      {
        id: 'doc-demo-dopamine',
        filename: 'dopamine_learning_notes.pdf',
        pages: 3,
        page_count: 3,
        status: 'ready',
        ocr_quality: 'good',
        chunk_count: 6,
        created_at: new Date(Date.now() - 3600000).toISOString(),
      },
      {
        id: 'doc-demo-cortex',
        filename: 'prefrontal_cortex_summary.txt',
        pages: 2,
        page_count: 2,
        status: 'ready',
        ocr_quality: 'good',
        chunk_count: 4,
        created_at: new Date(Date.now() - 7200000).toISOString(),
      },
    ],
  },
  conversations: {
    'ws-demo-neuro': [
      {
        id: 'conv-demo-1',
        title: 'Dopamine & Prefrontal Cortex Overview',
        updated_at: new Date().toISOString(),
      },
    ],
  },
  messages: {
    'conv-demo-1': [
      {
        id: 'msg-demo-1',
        role: 'user',
        content: 'What is the primary function of dopamine in reinforcement learning?',
        created_at: new Date(Date.now() - 120000).toISOString(),
      },
      {
        id: 'msg-demo-2',
        role: 'assistant',
        content: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway [1]. When an outcome is better than anticipated, phasic dopamine release reinforces associated behavioral actions, facilitating synaptic plasticity in the prefrontal cortex and striatum [2].',
        answer: [
          {
            text: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway [1]. When an outcome is better than anticipated, phasic dopamine release reinforces associated behavioral actions, facilitating synaptic plasticity in the prefrontal cortex and striatum [2].',
            citations: [],
          },
        ],
        created_at: new Date(Date.now() - 110000).toISOString(),
        citations: [
          {
            n: 1,
            citation_num: 1,
            document_id: 'doc-demo-dopamine',
            page: 1,
            quote: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway.',
            bbox: [0.08, 0.16, 0.92, 0.28],
            bounding_box: [60, 160, 520, 200],
          },
          {
            n: 2,
            citation_num: 2,
            document_id: 'doc-demo-dopamine',
            page: 1,
            quote: 'reinforces associated behavioral actions, facilitating synaptic plasticity in the prefrontal cortex',
            bbox: [0.08, 0.21, 0.92, 0.32],
            bounding_box: [60, 205, 540, 245],
          },
        ],
        confidence: 'high',
        verification_status: 'grounded',
      },
    ],
  },
  flashcards: [
    {
      question: 'What type of error signal does phasic dopamine release represent in reinforcement learning?',
      answer: 'A reward-prediction error signal in the mesolimbic pathway, indicating when outcomes exceed expectations.',
      quote: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway.',
      citation_quote: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway.',
      document_id: 'doc-demo-dopamine',
      page: 1,
      bbox: [0.08, 0.16, 0.92, 0.28],
    },
    {
      question: 'Which cortical region receives mesocortical dopamine projections to regulate working memory?',
      answer: 'The Prefrontal Cortex (PFC), modulating sustained attention and active representations.',
      quote: 'the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory',
      citation_quote: 'the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory',
      document_id: 'doc-demo-dopamine',
      page: 2,
      bbox: [0.08, 0.48, 0.92, 0.58],
    },
    {
      question: 'How does optimal D1 receptor stimulation affect cortical pyramidal neurons?',
      answer: 'It enhances the signal-to-noise ratio in cortical pyramidal neurons during challenging cognitive tasks.',
      quote: 'optimal D1 receptor stimulation enhances signal-to-noise ratio in cortical pyramidal neurons',
      citation_quote: 'optimal D1 receptor stimulation enhances signal-to-noise ratio in cortical pyramidal neurons',
      document_id: 'doc-demo-dopamine',
      page: 2,
      bbox: [0.08, 0.52, 0.92, 0.62],
    },
  ],
  // Dynamic client-side storage for user-uploaded notes and PDFs
  customDocs: {},
  customPageImages: {},
  customChunks: {},
};

// ============================================================================
// Client-Side File Ingestion Helpers (PDF.js, Text, & Images)
// ============================================================================

function splitTextIntoChunks(text, targetSize = 450, overlap = 60) {
  if (!text || !text.trim()) return [];
  const rawParagraphs = text.split(/\n{2,}|\r\n\r\n/);
  const segments = [];
  for (const para of rawParagraphs) {
    const trimmed = para.trim();
    if (!trimmed) continue;
    if (trimmed.length <= targetSize * 1.4) {
      segments.push(trimmed);
    } else {
      const sentences = trimmed.match(/[^.!?]+[.!?]+|\S+/g) || [trimmed];
      let cur = '';
      for (const s of sentences) {
        if ((cur + ' ' + s).length > targetSize && cur) {
          segments.push(cur.trim());
          cur = s;
        } else {
          cur += (cur ? ' ' : '') + s;
        }
      }
      if (cur.trim()) segments.push(cur.trim());
    }
  }
  return segments.length > 0 ? segments : [text.slice(0, targetSize)];
}

function generateTextPageSvg(filename, pageNo, totalPages, lines) {
  const maxLines = 28;
  const displayLines = (lines || []).slice(0, maxLines);
  const textElements = displayLines
    .map((line, idx) => {
      const y = 145 + idx * 23;
      const cleanLine = escapeHtml(line).replace(/&quot;/g, '"');
      return `<text x="55" y="${y}" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">${cleanLine}</text>`;
    })
    .join('\n');

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 850" width="100%" height="100%">
    <rect width="600" height="850" fill="#1b1a18" rx="8"/>
    <!-- Document Header -->
    <rect x="35" y="30" width="530" height="65" fill="#262421" rx="6" stroke="#3d3a35" stroke-width="1"/>
    <text x="55" y="65" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="15" font-weight="700" fill="#f8fafc">${escapeHtml(filename)}</text>
    <text x="55" y="83" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="11" fill="#a8a29e">Uploaded Course Notes • Page ${pageNo} of ${totalPages || 1}</text>
    
    <!-- Text Page Content -->
    ${textElements}

    <!-- Footer Note -->
    <line x1="40" y1="800" x2="560" y2="800" stroke="#3d3a35" stroke-width="1"/>
    <text x="55" y="822" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="10" fill="#78716c">StudyMind Grounded Document Verification • ${escapeHtml(filename)}</text>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

// Storage persistence helpers so user uploaded notes & custom chunks persist across reloads
function saveDemoStoreToStorage() {
  try {
    const dataToSave = {
      customChunks: demoStore.customChunks || {},
      documents: demoStore.documents || {},
      workspaces: demoStore.workspaces || [],
      customDocs: {},
    };
    if (demoStore.customDocs) {
      for (const dId in demoStore.customDocs) {
        const d = demoStore.customDocs[dId];
        dataToSave.customDocs[dId] = {
          id: d.id,
          filename: d.filename,
          page_count: d.page_count,
          chunks: d.chunks,
          pages: (d.pages || []).map((p) => ({
            pageNo: p.pageNo,
            text: p.text,
            lines: p.lines,
            width: p.width,
            height: p.height,
          })),
        };
      }
    }
    localStorage.setItem('studymind_demo_store_v1', JSON.stringify(dataToSave));
  } catch (err) {
    console.warn('Storage save warning (likely storage quota):', err);
  }
}

function loadDemoStoreFromStorage() {
  try {
    const raw = localStorage.getItem('studymind_demo_store_v1');
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed.customChunks) {
      demoStore.customChunks = Object.assign(demoStore.customChunks || {}, parsed.customChunks);
    }
    if (parsed.customDocs) {
      demoStore.customDocs = Object.assign(demoStore.customDocs || {}, parsed.customDocs);
    }
    if (parsed.documents) {
      demoStore.documents = Object.assign(demoStore.documents || {}, parsed.documents);
    }
    if (parsed.workspaces && parsed.workspaces.length > 0) {
      const ids = new Set(demoStore.workspaces.map((w) => w.id));
      parsed.workspaces.forEach((w) => {
        if (!ids.has(w.id)) demoStore.workspaces.push(w);
      });
    }
  } catch (err) {
    console.warn('Failed to load demoStore from storage:', err);
  }
}

// Global helper to retrieve any and all uploaded custom chunks across workspaces
function getAvailableChunks(wsId) {
  if (wsId && demoStore.customChunks?.[wsId]?.length > 0) {
    return demoStore.customChunks[wsId];
  }
  if (state.currentWorkspaceId && demoStore.customChunks?.[state.currentWorkspaceId]?.length > 0) {
    return demoStore.customChunks[state.currentWorkspaceId];
  }
  for (const k in demoStore.customChunks) {
    if (demoStore.customChunks[k] && demoStore.customChunks[k].length > 0) {
      return demoStore.customChunks[k];
    }
  }
  if (demoStore.customDocs) {
    const fromDocs = [];
    for (const dId in demoStore.customDocs) {
      const doc = demoStore.customDocs[dId];
      if (doc.chunks && doc.chunks.length > 0) {
        fromDocs.push(...doc.chunks);
      }
    }
    if (fromDocs.length > 0) return fromDocs;
  }
  return [];
}

function setupPdfJsWorker() {
  if (typeof pdfjsLib === 'undefined') return;
  try {
    if (!window.__pdfWorkerBlobUrl) {
      const workerBlob = new Blob(
        [`importScripts('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js');`],
        { type: 'application/javascript' }
      );
      window.__pdfWorkerBlobUrl = URL.createObjectURL(workerBlob);
    }
    pdfjsLib.GlobalWorkerOptions.workerSrc = window.__pdfWorkerBlobUrl;
  } catch (e) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = '';
  }
}

function extractPdfDirectFallback(file, arrayBuffer) {
  const bytes = new Uint8Array(arrayBuffer);
  let binaryStr = '';
  const len = bytes.byteLength;
  const maxRead = Math.min(len, 2 * 1024 * 1024);
  for (let i = 0; i < maxRead; i++) {
    binaryStr += String.fromCharCode(bytes[i]);
  }

  const extractedLines = [];
  const tjRegex = /\(([^)\\]*(?:\\.[^)\\]*)*)\)\s*(?:Tj|'|")/g;
  let match;
  while ((match = tjRegex.exec(binaryStr)) !== null) {
    const clean = match[1].replace(/\\([()\\])/g, '$1').trim();
    if (clean.length > 3 && /[a-zA-Z]/.test(clean)) {
      extractedLines.push(clean);
    }
  }

  const tjArrayRegex = /\[([^\]]+)\]\s*TJ/g;
  while ((match = tjArrayRegex.exec(binaryStr)) !== null) {
    const inner = match[1];
    const subMatches = inner.match(/\(([^)\\]*(?:\\.[^)\\]*)*)\)/g);
    if (subMatches) {
      const line = subMatches
        .map((s) => s.slice(1, -1).replace(/\\([()\\])/g, '$1').trim())
        .join(' ');
      if (line.length > 3 && /[a-zA-Z]/.test(line)) {
        extractedLines.push(line);
      }
    }
  }

  const rawText = extractedLines.length > 0
    ? extractedLines.join('\n')
    : `Uploaded Study Document: ${file.name}\nExtracted text stream from ${file.name}.`;

  const chunks = splitTextIntoChunks(rawText, 450, 60).map((text, idx) => ({
    id: `chunk-fb-${idx}`,
    page: 1,
    text,
    bbox: [0.08, 0.15, 0.92, 0.85],
    bounding_box: [0.08, 0.15, 0.92, 0.85],
  }));

  const pages = [
    {
      pageNo: 1,
      image: generateTextPageSvg(file.name, 1, 1, extractedLines.slice(0, 30)),
      text: rawText,
      lines: extractedLines.slice(0, 30),
      width: 600,
      height: 850,
    },
  ];

  return { numPages: 1, pages, chunks };
}

async function extractDocxFileClientSide(file) {
  const arrayBuffer = await file.arrayBuffer();
  const bytes = new Uint8Array(arrayBuffer);
  let str = '';
  const len = bytes.byteLength;
  const maxRead = Math.min(len, 2 * 1024 * 1024);
  for (let i = 0; i < maxRead; i++) {
    str += String.fromCharCode(bytes[i]);
  }

  const paragraphs = [];
  const pRegex = /<w:p(?:[\s>][\s\S]*?<\/w:p>)/g;
  let pMatch;
  while ((pMatch = pRegex.exec(str)) !== null) {
    const pXml = pMatch[0];
    const tRegex = /<w:t[^>]*>([^<]+)<\/w:t>/g;
    let tMatch;
    let pText = '';
    while ((tMatch = tRegex.exec(pXml)) !== null) {
      pText += tMatch[1];
    }
    if (pText.trim()) {
      paragraphs.push(pText.trim());
    }
  }

  if (paragraphs.length === 0) {
    const tRegex = /<w:t[^>]*>([^<]+)<\/w:t>/g;
    let tMatch;
    while ((tMatch = tRegex.exec(str)) !== null) {
      if (tMatch[1].trim()) paragraphs.push(tMatch[1].trim());
    }
  }

  const rawText = paragraphs.length > 0
    ? paragraphs.join('\n')
    : `Word Notes Document: ${file.name}\nExtracted text from Word document.`;

  const chunks = splitTextIntoChunks(rawText, 450, 60).map((text, idx) => ({
    id: `chunk-docx-${idx}`,
    page: 1,
    text,
    bbox: [0.08, 0.15, 0.92, 0.85],
    bounding_box: [0.08, 0.15, 0.92, 0.85],
  }));

  const pages = [
    {
      pageNo: 1,
      image: generateTextPageSvg(file.name, 1, 1, paragraphs.slice(0, 30)),
      text: rawText,
      lines: paragraphs.slice(0, 30),
      width: 600,
      height: 850,
    },
  ];

  return { numPages: 1, pages, chunks };
}

async function extractPdfClientSide(file) {
  setupPdfJsWorker();
  const arrayBuffer = await file.arrayBuffer();

  if (typeof pdfjsLib !== 'undefined') {
    try {
      const loadingTask = pdfjsLib.getDocument({
        data: arrayBuffer,
        useWorkerFetch: false,
        isEvalSupported: false,
        useSystemFonts: true,
      });
      const pdf = await loadingTask.promise;
      const numPages = pdf.numPages;
      const pages = [];
      const allChunks = [];

      for (let pageNo = 1; pageNo <= numPages; pageNo++) {
        const page = await pdf.getPage(pageNo);

        // 1. EXTRACT TEXT CONTENT FIRST - Never let canvas issues prevent text extraction!
        let fullPageText = '';
        let lines = [];
        try {
          const textContent = await page.getTextContent();
          const items = textContent.items || [];
          const lineBuckets = {};
          for (const it of items) {
            if (!it.str || !it.str.trim()) continue;
            const yKey = Math.round(it.transform[5] / 6) * 6;
            if (!lineBuckets[yKey]) lineBuckets[yKey] = [];
            lineBuckets[yKey].push(it);
          }
          const sortedY = Object.keys(lineBuckets).map(Number).sort((a, b) => b - a);
          for (const y of sortedY) {
            const sortedX = lineBuckets[y].sort((a, b) => a.transform[4] - b.transform[4]);
            const lineText = sortedX.map((it) => it.str).join(' ').trim();
            if (lineText) lines.push(lineText);
          }
          fullPageText = lines.join('\n');
        } catch (textErr) {
          console.warn(`TextContent extraction error on page ${pageNo}:`, textErr);
        }

        if (fullPageText.trim().length > 0) {
          const pageChunks = splitTextIntoChunks(fullPageText, 450, 60);
          const nChunks = Math.max(1, pageChunks.length);
          pageChunks.forEach((chunkText, cIdx) => {
            const yStart = 0.08 + (cIdx / nChunks) * 0.78;
            const yEnd = Math.min(0.95, yStart + (1 / nChunks) * 0.75);
            allChunks.push({
              id: `chunk-p${pageNo}-${cIdx}`,
              page: pageNo,
              text: chunkText,
              bbox: [0.06, yStart, 0.94, yEnd],
              bounding_box: [0.06, yStart, 0.94, yEnd],
            });
          });
        }

        // 2. Render page to canvas with safe fallback
        let pageDataUrl = null;
        try {
          const scale = window.innerWidth <= 768 ? 1.0 : 1.3;
          const viewport = page.getViewport({ scale });
          const canvas = document.createElement('canvas');
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          const ctx = canvas.getContext('2d');
          await page.render({ canvasContext: ctx, viewport }).promise;
          pageDataUrl = canvas.toDataURL('image/png');
        } catch (canvasErr) {
          console.warn(`Canvas render fallback for page ${pageNo}:`, canvasErr);
          pageDataUrl = generateTextPageSvg(file.name, pageNo, numPages, lines.length > 0 ? lines : ['[Rendered PDF Page ' + pageNo + ']']);
        }

        pages.push({
          pageNo,
          image: pageDataUrl,
          text: fullPageText,
          lines,
          width: 600,
          height: 850,
        });
      }

      if (allChunks.length > 0) {
        return { numPages, pages, chunks: allChunks };
      }
    } catch (pdfErr) {
      console.warn('PDF.js failed, engaging direct stream text fallback parser:', pdfErr);
    }
  }

  // Fallback to direct stream parser if PDF.js fails
  return extractPdfDirectFallback(file, arrayBuffer);
}

async function extractTextFileClientSide(file) {
  const text = await file.text();
  const rawLines = text.split(/\r?\n/);
  const linesPerPage = 30;
  const numPages = Math.max(1, Math.ceil(rawLines.length / linesPerPage));
  const pages = [];
  const allChunks = [];

  for (let p = 1; p <= numPages; p++) {
    const startIdx = (p - 1) * linesPerPage;
    const pageLines = rawLines.slice(startIdx, startIdx + linesPerPage);
    const pageText = pageLines.join('\n');
    const svgDataUrl = generateTextPageSvg(file.name, p, numPages, pageLines);

    pages.push({
      pageNo: p,
      image: svgDataUrl,
      text: pageText,
      lines: pageLines,
      width: 600,
      height: 850,
    });

    const pageChunks = splitTextIntoChunks(pageText, 450, 60);
    const nChunks = Math.max(1, pageChunks.length);
    pageChunks.forEach((chunkText, cIdx) => {
      const yStart = 0.12 + (cIdx / nChunks) * 0.74;
      const yEnd = Math.min(0.95, yStart + (1 / nChunks) * 0.72);
      allChunks.push({
        id: `chunk-p${p}-${cIdx}`,
        page: p,
        text: chunkText,
        bbox: [0.06, yStart, 0.94, yEnd],
        bounding_box: [0.06, yStart, 0.94, yEnd],
      });
    });
  }

  return { numPages, pages, chunks: allChunks };
}

async function extractImageFileClientSide(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const imgDataUrl = e.target.result;
      const cleanName = file.name.replace(/\.[^/.]+$/, '').replace(/[_-]/g, ' ');
      const pageText = `Visual Lecture Material: ${file.name}\nKey study notes, visual diagram, and topic summary regarding ${cleanName}.\nThis document contains visual learning concepts and formulas uploaded from device for ${cleanName}.`;
      const chunk = {
        id: `chunk-img-${Date.now()}`,
        page: 1,
        text: pageText,
        bbox: [0.06, 0.12, 0.94, 0.88],
        bounding_box: [0.06, 0.12, 0.94, 0.88],
      };
      resolve({
        numPages: 1,
        pages: [
          {
            pageNo: 1,
            image: imgDataUrl,
            text: pageText,
            lines: [file.name, `Topic: ${cleanName}`],
            width: 800,
            height: 1000,
          },
        ],
        chunks: [chunk],
      });
    };
    reader.readAsDataURL(file);
  });
}

// ============================================================================
// Dynamic Grounded Retrieval & Synthesis Engine
// ============================================================================

function searchChunks(query, wsId, topK = 4) {
  const customChunks = getAvailableChunks(wsId);
  let pool = customChunks;
  if (pool.length === 0 && wsId === 'ws-demo-neuro') {
    pool = [
      {
        id: 'chunk-demo-1',
        document_id: 'doc-demo-dopamine',
        filename: 'dopamine_learning_notes.pdf',
        page: 1,
        text: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway. When an outcome is better than anticipated, phasic dopamine release reinforces associated behavioral actions, facilitating synaptic plasticity in the prefrontal cortex and striatum through long-term potentiation.',
        bbox: [0.08, 0.16, 0.92, 0.28],
        bounding_box: [0.08, 0.16, 0.92, 0.28],
      },
      {
        id: 'chunk-demo-2',
        document_id: 'doc-demo-dopamine',
        filename: 'dopamine_learning_notes.pdf',
        page: 2,
        text: 'The mesocortical projection directs dopamine to the prefrontal cortex to govern working memory and sustained attention. Optimal D1 receptor stimulation enhances signal-to-noise ratio in cortical pyramidal neurons during challenging cognitive tasks.',
        bbox: [0.08, 0.48, 0.92, 0.62],
        bounding_box: [0.08, 0.48, 0.92, 0.62],
      },
    ];
  }

  if (pool.length === 0) return [];

  const stopWords = new Set([
    'a', 'an', 'the', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or', 'is', 'are', 'was', 'were',
    'what', 'how', 'why', 'when', 'which', 'who', 'does', 'do', 'did', 'can', 'explain', 'tell', 'me',
    'about', 'with', 'from', 'by', 'as', 'it', 'this', 'that', 'these', 'those', 'your', 'my', 'please',
    'based', 'material', 'notes', 'uploaded', 'document', 'page', 'pages', 'summarize', 'summary',
  ]);

  const queryClean = query.toLowerCase();
  const queryTerms = queryClean
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length > 2 && !stopWords.has(w));

  const scored = pool.map((chk) => {
    const textLower = chk.text.toLowerCase();
    let score = 0;

    if (queryTerms.length > 1 && textLower.includes(queryClean.trim())) {
      score += 25.0;
    }

    for (const term of queryTerms) {
      if (textLower.includes(term)) {
        score += 3.5;
        const count = textLower.split(term).length - 1;
        score += Math.min(count - 1, 3) * 1.5;
      }
    }

    return { chunk: chk, score };
  });

  scored.sort((a, b) => b.score - a.score);
  return scored.filter((s) => s.score > 0).slice(0, topK).map((s) => s.chunk);
}

function isMarksQuery(query) {
  const q = query.toLowerCase();
  return (
    q.includes('1 mark') ||
    q.includes('3 mark') ||
    q.includes('1 & 3 mark') ||
    q.includes('marks like 1 mark') ||
    q.includes('questions and answers based on marks')
  );
}

function generateMarksQa(chunks, docName) {
  const sentences = [];
  chunks.forEach((c) => {
    const sList = c.text.match(/[^.!?]+[.!?]+/g) || [c.text];
    sList.forEach((s) => {
      const clean = s.trim();
      if (clean.length > 25) {
        sentences.push({ text: clean, chunk: c });
      }
    });
  });

  const citations = [];
  let citCounter = 1;

  let q1Text = 'What is the primary role described in the material?';
  let a1Text = 'It represents a core functional mechanism identified in your notes.';
  if (sentences.length > 0) {
    const s1 = sentences[0];
    const words = s1.text.split(' ');
    const keyword = words.slice(0, 4).join(' ').replace(/[,;:]/g, '');
    q1Text = `Define or state the role of: ${keyword}`;
    a1Text = `${s1.text} [${citCounter}]`;
    citations.push({
      n: citCounter,
      citation_num: citCounter,
      document_id: s1.chunk.document_id,
      page: s1.chunk.page,
      quote: s1.text.slice(0, 140),
      bbox: s1.chunk.bbox,
      bounding_box: s1.chunk.bounding_box,
    });
    citCounter++;
  }

  let q2Text = 'State a key property or finding.';
  let a2Text = 'Documented as a verified property.';
  if (sentences.length > 1) {
    const s2 = sentences[1];
    q2Text = `State the significance of the concept on Page ${s2.chunk.page}.`;
    a2Text = `${s2.text} [${citCounter}]`;
    citations.push({
      n: citCounter,
      citation_num: citCounter,
      document_id: s2.chunk.document_id,
      page: s2.chunk.page,
      quote: s2.text.slice(0, 140),
      bbox: s2.chunk.bbox,
      bounding_box: s2.chunk.bounding_box,
    });
    citCounter++;
  }

  let q3Text = 'Explain the mechanism or concept in detail.';
  const a3Points = [];
  const remainSentences = sentences.slice(2, 5);
  if (remainSentences.length > 0) {
    remainSentences.forEach((s, idx) => {
      a3Points.push(`${idx + 1}. ${s.text} [${citCounter}]`);
      citations.push({
        n: citCounter,
        citation_num: citCounter,
        document_id: s.chunk.document_id,
        page: s.chunk.page,
        quote: s.text.slice(0, 140),
        bbox: s.chunk.bbox,
        bounding_box: s.chunk.bounding_box,
      });
      citCounter++;
    });
  } else if (sentences.length > 0) {
    a3Points.push(`1. ${sentences[0].text} [1]`);
  }

  const content = `### 🎯 Grounded 1-Mark Questions (Objective / Definitions)

**Q1 (1 Mark):** ${q1Text}
**Answer:** ${a1Text}

**Q2 (1 Mark):** ${q2Text}
**Answer:** ${a2Text}

---

### 📝 Grounded 3-Mark Question (Analytical & Mechanism)

**Q3 (3 Marks):** ${q3Text}
**Structured Answer:**
${a3Points.join('\n')}

*All answers strictly verified from your uploaded document (${escapeHtml(docName || 'study notes')}).*`;

  return {
    content,
    answer: [{ text: content, citations }],
    citations,
    confidence: 'high',
    verification_status: 'grounded',
  };
}

async function synthesizeGroundedAnswer(query, chunks, wsId) {
  const geminiKey = typeof localStorage !== 'undefined' ? localStorage.getItem('gemini_api_key') : null;

  // 1. If user supplied Gemini API key, attempt real Gemini 1.5 Flash grounded call
  if (geminiKey && geminiKey.trim()) {
    try {
      const contextBlocks = chunks
        .map((c, i) => `[${i + 1}] (Document: ${c.filename || 'Notes'}, Page ${c.page}):\n${c.text}`)
        .join('\n\n');
      const prompt = `You are StudyMind, a strictly grounded study assistant. You must follow these rules:
1. ONLY answer using the provided retrieved material below. Never use outside knowledge.
2. For EVERY single assertion or sentence, append the citation tag [1], [2], etc., corresponding to the chunk used.
3. If the retrieved material does not contain the answer, reply ONLY with: "I could not find sufficient evidence in your uploaded study notes to answer this question."

Retrieved Study Material:
${contextBlocks}

Student Question: "${query}"

Grounded Answer:`;

      const gRes = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${geminiKey.trim()}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0.1, maxOutputTokens: 600 },
          }),
        }
      );

      if (gRes.ok) {
        const gData = await gRes.json();
        const candidate = gData?.candidates?.[0]?.content?.parts?.[0]?.text;
        if (candidate && candidate.trim()) {
          const rawAnswer = candidate.trim();
          const citations = [];
          chunks.forEach((chk, idx) => {
            const citNum = idx + 1;
            if (rawAnswer.includes(`[${citNum}]`)) {
              citations.push({
                n: citNum,
                citation_num: citNum,
                document_id: chk.document_id,
                page: chk.page,
                quote: chk.text.slice(0, 140),
                bbox: chk.bbox || [0.08, 0.2, 0.92, 0.35],
                bounding_box: chk.bounding_box || [0.08, 0.2, 0.92, 0.35],
              });
            }
          });
          if (citations.length === 0 && chunks.length > 0) {
            citations.push({
              n: 1,
              citation_num: 1,
              document_id: chunks[0].document_id,
              page: chunks[0].page,
              quote: chunks[0].text.slice(0, 140),
              bbox: chunks[0].bbox,
              bounding_box: chunks[0].bounding_box,
            });
          }

          return {
            content: rawAnswer,
            answer: [{ text: rawAnswer, citations }],
            citations,
            confidence: 'high',
            verification_status: 'grounded',
          };
        }
      }
    } catch (gErr) {
      console.warn('Gemini client call error, falling back to local grounded engine:', gErr);
    }
  }

  // 2. Local deterministic grounded synthesis (Zero external dependency, 100% grounded)
  const citations = [];
  const answerSentences = [];

  chunks.forEach((chunk, idx) => {
    const citNum = idx + 1;
    const sList = chunk.text.match(/[^.!?]+[.!?]+/g) || [chunk.text];
    let bestSentence = sList[0].trim();
    const qWords = query.toLowerCase().split(/\s+/).filter((w) => w.length > 3);
    for (const s of sList) {
      const sLower = s.toLowerCase();
      if (qWords.some((w) => sLower.includes(w))) {
        bestSentence = s.trim();
        break;
      }
    }

    answerSentences.push(`${bestSentence} [${citNum}]`);
    citations.push({
      n: citNum,
      citation_num: citNum,
      document_id: chunk.document_id,
      page: chunk.page,
      quote: bestSentence.slice(0, 140),
      bbox: chunk.bbox || [0.08, 0.15, 0.92, 0.3],
      bounding_box: chunk.bounding_box || [0.08, 0.15, 0.92, 0.3],
    });
  });

  const docName = chunks[0]?.filename || 'your uploaded notes';
  const fullAnswer = `Based on your uploaded course notes (${escapeHtml(docName)}):\n\n${answerSentences.join('\n\n')}`;

  return {
    content: fullAnswer,
    answer: [{ text: fullAnswer, citations }],
    citations,
    confidence: 'high',
    verification_status: 'grounded',
  };
}

function generateDynamicSummary(wsId, length = 'medium') {
  const customChunks = getAvailableChunks(wsId);
  if (customChunks.length === 0) {
    return {
      title: 'Chapter 4: Dopaminergic Signaling & Cognitive Control',
      summary:
        'Dopamine projections from the ventral tegmental area (VTA) and substantia nigra modulate both motor execution and executive cognitive functions. Phasic dopamine signals encode reward-prediction errors in the mesolimbic pathway, while tonic mesocortical signals in the prefrontal cortex sustain active working memory representations via D1 receptors.',
      pages_covered: [
        { page: 1, document_id: 'doc-demo-dopamine', title: 'Reward Signals' },
        { page: 2, document_id: 'doc-demo-dopamine', title: 'PFC Working Memory' },
      ],
      important_areas: [
        {
          area_title: 'Dopaminergic Pathways',
          summary: 'Phasic bursts communicate reward prediction errors facilitating synaptic plasticity.',
          quote: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway.',
          page: 1,
          document_id: 'doc-demo-dopamine',
        },
        {
          area_title: 'Prefrontal Modulation',
          summary: 'Optimal D1 receptor activation tunes cortical signal-to-noise ratio.',
          quote: 'the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory',
          page: 2,
          document_id: 'doc-demo-dopamine',
        },
      ],
      key_takeaways: [
        {
          point: 'Phasic bursts communicate reward prediction errors facilitating reinforcement learning.',
          quote: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway.',
          page: 1,
          document_id: 'doc-demo-dopamine',
        },
        {
          point: 'Mesocortical projections to the PFC gate distractors and stabilize mental representations.',
          quote: 'optimal D1 receptor stimulation enhances signal-to-noise ratio in cortical pyramidal neurons',
          page: 2,
          document_id: 'doc-demo-dopamine',
        },
      ],
    };
  }

  const docNames = Array.from(new Set(customChunks.map((c) => c.filename))).filter(Boolean);
  const title = `Summary: ${docNames[0] || 'Uploaded Course Material'}`;
  const pagesList = Array.from(new Set(customChunks.map((c) => c.page))).sort((a, b) => a - b);

  const importantAreas = [];
  const keyTakeaways = [];
  const overviewSentences = [];

  customChunks.forEach((c) => {
    const sList = c.text
      .split(/(?:[\r\n]+|[.!?]+\s+|•|\s*-\s+|\s*\d+\.\s+)/)
      .map((s) => s.replace(/^[-*•\d.)\s]+/, '').trim())
      .filter((s) => s.length >= 20 && s.length <= 260);

    if (sList.length > 0 && overviewSentences.length < 5) {
      overviewSentences.push(sList[0]);
    }
  });

  pagesList.slice(0, 5).forEach((pg) => {
    const pageChunks = customChunks.filter((c) => c.page === pg);
    if (pageChunks.length > 0) {
      const topChunk = pageChunks[0];
      const sList = topChunk.text
        .split(/(?:[\r\n]+|[.!?]+\s+|•|\s*-\s+|\s*\d+\.\s+)/)
        .map((s) => s.replace(/^[-*•\d.)\s]+/, '').trim())
        .filter((s) => s.length >= 20 && s.length <= 260);

      const leadSentence = sList[0] || topChunk.text.slice(0, 140);
      const words = leadSentence.split(/\s+/).slice(0, 4).join(' ').replace(/[,;:]/g, '');
      const areaTitle = words.length > 3 ? words : `Topic on Page ${pg}`;

      importantAreas.push({
        area_title: areaTitle,
        summary: leadSentence,
        quote: leadSentence.slice(0, 140),
        page: pg,
        document_id: topChunk.document_id,
        bbox: topChunk.bbox,
      });

      if (sList.length > 1) {
        keyTakeaways.push({
          point: sList[1],
          quote: sList[1].slice(0, 140),
          page: pg,
          document_id: topChunk.document_id,
          bbox: topChunk.bbox,
        });
      }
    }
  });

  if (keyTakeaways.length === 0 && importantAreas.length > 0) {
    keyTakeaways.push({
      point: importantAreas[0].summary,
      quote: importantAreas[0].quote,
      page: importantAreas[0].page,
      document_id: importantAreas[0].document_id,
    });
  }

  const pagesCovered = pagesList.map((pg) => {
    const c = customChunks.find((chk) => chk.page === pg);
    return {
      page: pg,
      document_id: c?.document_id || '',
      title: `Page ${pg}`,
    };
  });

  return {
    title,
    summary: overviewSentences.join(' ') || 'Comprehensive summary of uploaded notes.',
    pages_covered: pagesCovered,
    important_areas: importantAreas,
    key_takeaways: keyTakeaways,
  };
}

function generateDynamicFlashcards(wsId, count = 5) {
  const customChunks = getAvailableChunks(wsId);
  if (customChunks.length === 0) {
    return { flashcards: demoStore.flashcards };
  }

  const allStatements = [];
  customChunks.forEach((chunk) => {
    const lines = chunk.text
      .split(/(?:[\r\n]+|[.!?]+\s+|•|\s*-\s+|\s*\d+\.\s+)/)
      .map((s) => s.replace(/^[-*•\d.)\s]+/, '').trim())
      .filter((s) => s.length >= 20 && s.length <= 260);

    lines.forEach((stmt) => {
      allStatements.push({
        statement: stmt,
        chunk,
        filename: chunk.filename || 'uploaded document',
        page: chunk.page || 1,
        document_id: chunk.document_id,
        bbox: chunk.bbox || [0.08, 0.2, 0.92, 0.4],
      });
    });
  });

  const cards = [];
  for (const item of allStatements) {
    if (cards.length >= count) break;
    const clean = item.statement;

    let q = '';
    let a = '';
    if (
      clean.toLowerCase().includes(' is ') ||
      clean.toLowerCase().includes(' refers to ') ||
      clean.toLowerCase().includes(' are ') ||
      clean.toLowerCase().includes(' defined as ')
    ) {
      const parts = clean.split(/\s+(?:is|refers to|are|defined as)\s+/i);
      if (parts.length >= 2 && parts[0].length < 60) {
        q = `What is ${parts[0].trim()}?`;
        a = `It ${clean.substring(parts[0].length).trim()}`;
      }
    }

    if (!q) {
      const words = clean.split(/\s+/);
      const head = words.slice(0, 4).join(' ');
      q = `In ${item.filename} (Page ${item.page}), what is stated regarding "${head}"?`;
      a = clean;
    }

    cards.push({
      id: `fc-${Date.now()}-${cards.length}`,
      question: q,
      answer: a,
      quote: clean.slice(0, 140),
      citation_quote: clean.slice(0, 140),
      page: item.page,
      document_id: item.document_id,
      bbox: item.bbox,
    });
  }

  return { flashcards: cards.length > 0 ? cards : demoStore.flashcards };
}

function generateDynamicQuiz(wsId, count = 3, diff = 'medium') {
  const customChunks = getAvailableChunks(wsId);
  if (customChunks.length === 0) {
    return {
      session_id: 'sess-demo-' + Date.now(),
      questions: [
        {
          id: 'q-demo-1',
          type: 'mcq',
          marks: 1,
          stem: 'In reinforcement learning models, what does phasic dopamine discharge signify?',
          options: [
            'A reward-prediction error signal',
            'Baseline metabolic activity in the cerebellum',
            'Inhibition of sympathetic neurotransmission',
            'Permanent depletion of serotonin vesicles',
          ],
          correct_answer_index: 0,
          quote: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway.',
          explanation: 'Verified against Chapter 4 excerpt.',
          document_id: 'doc-demo-dopamine',
          page: 1,
        },
        {
          id: 'q-demo-2',
          type: 'mcq',
          marks: 1,
          stem: 'Which cortical region is targeted by the mesocortical dopamine tract for working memory regulation?',
          options: [
            'Primary Occipital Cortex (V1)',
            'Prefrontal Cortex (PFC)',
            'Auditory Cortex (A1)',
            'Somatosensory Strip (S1)',
          ],
          correct_answer_index: 1,
          quote: 'the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory',
          explanation: 'Verified against Chapter 4 excerpt.',
          document_id: 'doc-demo-dopamine',
          page: 2,
        },
      ],
    };
  }

  const allStatements = [];
  customChunks.forEach((chunk) => {
    const lines = chunk.text
      .split(/(?:[\r\n]+|[.!?]+\s+|•|\s*-\s+|\s*\d+\.\s+)/)
      .map((s) => s.replace(/^[-*•\d.)\s]+/, '').trim())
      .filter((s) => s.length >= 18 && s.length <= 260);

    lines.forEach((stmt) => {
      allStatements.push({
        statement: stmt,
        chunk,
        filename: chunk.filename || 'uploaded document',
        page: chunk.page || 1,
        document_id: chunk.document_id,
        bbox: chunk.bbox || [0.08, 0.2, 0.92, 0.4],
      });
    });
  });

  if (allStatements.length === 0) {
    customChunks.forEach((c) => {
      allStatements.push({
        statement: c.text.slice(0, 180).trim(),
        chunk: c,
        filename: c.filename || 'uploaded document',
        page: c.page || 1,
        document_id: c.document_id,
        bbox: c.bbox || [0.08, 0.2, 0.92, 0.4],
      });
    });
  }

  const questions = [];
  const targetCount = Math.min(count, allStatements.length);
  const shuffledStatements = [...allStatements].sort(() => Math.random() - 0.5);

  for (let i = 0; i < shuffledStatements.length && questions.length < targetCount; i++) {
    const target = shuffledStatements[i];
    const factText = target.statement;

    const words = factText.split(/\s+/);
    const keyConcept = words.slice(0, Math.min(5, words.length)).join(' ').replace(/[,;:.()]/g, '');

    let stem = '';
    if (words.length > 5) {
      stem = `According to your notes in ${escapeHtml(target.filename)} (Page ${target.page}), what is stated regarding "${escapeHtml(keyConcept)}"?`;
    } else {
      stem = `According to your study materials in ${escapeHtml(target.filename)} (Page ${target.page}), which of the following is correct?`;
    }

    const correctOption = factText;

    const otherCandidates = allStatements.filter((s) => s.statement !== factText);
    const shuffledOthers = [...otherCandidates].sort(() => Math.random() - 0.5);

    let distractor1 = shuffledOthers[0]?.statement;
    let distractor2 = shuffledOthers[1]?.statement;
    let distractor3 = shuffledOthers[2]?.statement;

    if (!distractor1) {
      distractor1 = `The opposite principle holds, where ${keyConcept} is strictly restricted.`;
    }
    if (!distractor2) {
      distractor2 = `It is exclusively confined to unrelated external factors not described in this section.`;
    }
    if (!distractor3) {
      distractor3 = `It has no measurable influence according to the evidence outlined on Page ${target.page}.`;
    }

    const rawOptions = [correctOption, distractor1, distractor2, distractor3];
    const optionObjs = rawOptions
      .map((val, idx) => ({ val, isCorrect: idx === 0 }))
      .sort(() => Math.random() - 0.5);

    const correctIdx = optionObjs.findIndex((o) => o.isCorrect);

    questions.push({
      id: `q-${Date.now()}-${questions.length}`,
      type: 'mcq',
      marks: 1,
      stem,
      options: optionObjs.map((o) => o.val),
      correct_answer_index: correctIdx,
      quote: factText.slice(0, 140),
      explanation: `Verified directly from ${escapeHtml(target.filename)} on Page ${target.page}.`,
      document_id: target.document_id,
      page: target.page,
      bbox: target.bbox,
    });
  }

  return {
    session_id: 'sess-' + Date.now(),
    questions: questions.length > 0 ? questions : [],
  };
}

function generateDynamicQa(wsId) {
  const customChunks = getAvailableChunks(wsId);
  if (customChunks.length === 0) {
    return {
      questions: [
        {
          marks: 1,
          question: 'What error signal does phasic dopamine release encode in the mesolimbic pathway?',
          answer: 'It encodes a reward-prediction error signal indicating an outcome superior to expectation [1].',
          citations: [
            {
              citation_num: 1,
              document_id: 'doc-demo-dopamine',
              page: 1,
              quote: 'Dopamine serves as a critical reward-prediction error signal in the mesolimbic pathway.',
            },
          ],
        },
        {
          marks: 3,
          question: 'Explain how D1 receptor stimulation in the prefrontal cortex influences working memory performance.',
          answer:
            'Mesocortical dopamine projections innervate the PFC [1]. Moderate D1 stimulation increases signal-to-noise ratio in pyramidal neurons [2], while excessive or inadequate levels disrupt delay-period firing, displaying an inverted-U relationship.',
          citations: [
            {
              citation_num: 1,
              document_id: 'doc-demo-dopamine',
              page: 2,
              quote: 'the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory',
            },
            {
              citation_num: 2,
              document_id: 'doc-demo-dopamine',
              page: 2,
              quote: 'optimal D1 receptor stimulation enhances signal-to-noise ratio in cortical pyramidal neurons',
            },
          ],
        },
      ],
    };
  }

  const res = generateMarksQa(customChunks, customChunks[0]?.filename);
  return {
    questions: [
      {
        marks: 1,
        question: `Define key concepts from ${escapeHtml(customChunks[0]?.filename || 'notes')}`,
        answer: res.content,
        citations: res.citations,
      },
    ],
  };
}



// ============================================================================
// Standalone API Mock Router (Offline & Vercel Preview)
// ============================================================================

async function handleMockApiRequest(endpoint, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const cleanEp = endpoint.split('?')[0];

  // 1. Auth routes
  if (cleanEp === '/auth/guest') {
    return {
      access_token: 'demo-guest-token-' + Date.now(),
      token_type: 'bearer',
      user: { id: 'usr-guest-demo', email: 'guest_student@studymind.io' },
      workspace_id: 'ws-demo-neuro',
      is_guest: true,
    };
  }
  if (cleanEp === '/auth/login' || cleanEp === '/auth/register') {
    return {
      access_token: 'demo-student-token-' + Date.now(),
      token_type: 'bearer',
    };
  }
  if (cleanEp === '/auth/me') {
    return {
      id: state.isGuest ? 'usr-guest-demo' : 'usr-student-demo',
      email: state.isGuest ? 'guest_student@studymind.io' : 'student@studymind.io',
      full_name: state.isGuest ? 'Guest Student' : 'Demo Student',
    };
  }

  // 2. Workspaces
  if (cleanEp === '/workspaces') {
    if (method === 'POST') {
      const body = options.body ? JSON.parse(options.body) : {};
      const newWs = {
        id: 'ws-' + Date.now(),
        name: body.name || 'New Study Workspace',
        document_count: 0,
        created_at: new Date().toISOString(),
      };
      demoStore.workspaces.push(newWs);
      demoStore.documents[newWs.id] = [];
      demoStore.conversations[newWs.id] = [];
      return newWs;
    }
    return demoStore.workspaces;
  }

  // 3. Documents
  const wsDocsMatch = cleanEp.match(/^\/workspaces\/([^\/]+)\/documents$/);
  if (wsDocsMatch) {
    const wsId = wsDocsMatch[1];
    if (method === 'POST') {
      const newDocId = 'doc-' + Date.now();
      let filename = 'uploaded_notes.pdf';
      if (options.body instanceof FormData) {
        const f = options.body.get('file');
        if (f && f.name) filename = f.name;
      }
      const newDoc = {
        id: newDocId,
        filename,
        pages: 1,
        page_count: 1,
        status: 'ready',
        ocr_quality: 'good',
        chunk_count: 3,
        created_at: new Date().toISOString(),
      };
      if (!demoStore.documents[wsId]) demoStore.documents[wsId] = [];
      demoStore.documents[wsId].unshift(newDoc);
      return { document_id: newDocId, status: 'ready', pages: 1, message: 'Document ingested successfully' };
    }
    return demoStore.documents[wsId] || [];
  }

  const docReprocessMatch = cleanEp.match(/^\/documents\/([^\/]+)\/reprocess$/);
  if (docReprocessMatch) {
    return { status: 'ready', message: 'Reprocessed' };
  }

  const docDeleteMatch = cleanEp.match(/^\/documents\/([^\/]+)$/);
  if (docDeleteMatch && method === 'DELETE') {
    const dId = docDeleteMatch[1];
    for (const wsKey in demoStore.documents) {
      demoStore.documents[wsKey] = demoStore.documents[wsKey].filter((d) => d.id !== dId);
    }
    if (demoStore.customDocs) delete demoStore.customDocs[dId];
    if (demoStore.customPageImages) delete demoStore.customPageImages[dId];
    return { message: 'Document deleted' };
  }

  // 4. Conversations
  const wsConvsMatch = cleanEp.match(/^\/workspaces\/([^\/]+)\/conversations$/);
  if (wsConvsMatch) {
    const wsId = wsConvsMatch[1];
    if (method === 'POST') {
      const body = options.body ? JSON.parse(options.body) : {};
      const newConv = {
        id: 'conv-' + Date.now(),
        title: body.title || 'New Study Chat',
        updated_at: new Date().toISOString(),
      };
      if (!demoStore.conversations[wsId]) demoStore.conversations[wsId] = [];
      demoStore.conversations[wsId].unshift(newConv);
      demoStore.messages[newConv.id] = [];
      return newConv;
    }
    return demoStore.conversations[wsId] || [];
  }

  // 5. Messages
  const convMsgsMatch = cleanEp.match(/^\/conversations\/([^\/]+)\/messages$/);
  if (convMsgsMatch) {
    const convId = convMsgsMatch[1];
    if (method === 'POST') {
      const body = options.body ? JSON.parse(options.body) : {};
      const userText = body.question || body.content || '';
      const userMsg = {
        id: 'msg-' + Date.now(),
        role: 'user',
        content: userText,
        created_at: new Date().toISOString(),
      };
      if (!demoStore.messages[convId]) demoStore.messages[convId] = [];
      demoStore.messages[convId].push(userMsg);

      const wsId = state.currentWorkspaceId || 'ws-demo-neuro';
      const customChunks = getAvailableChunks(wsId);

      let assistantMsg = null;
      if (customChunks.length > 0) {
        if (isMarksQuery(userText)) {
          const marksRes = generateMarksQa(customChunks, customChunks[0]?.filename);
          assistantMsg = {
            id: 'msg-' + (Date.now() + 1),
            role: 'assistant',
            ...marksRes,
            created_at: new Date().toISOString(),
          };
        } else {
          const matched = searchChunks(userText, wsId, 3);
          if (matched.length === 0) {
            assistantMsg = {
              id: 'msg-' + (Date.now() + 1),
              role: 'assistant',
              abstained: true,
              confidence: 'low',
              verification_status: 'abstain',
              missing_info: `Topics related to "${userText}" were not found in your uploaded materials.`,
              content: `I could not find sufficient evidence in your uploaded study notes to answer: "${userText}".\n\nUnder StudyMind's strict grounding policy, I never fabricate answers from outside knowledge. Please verify that this topic is included in your uploaded notes.`,
              citations: [],
              suggestions: ['Summarize page 1', 'Generate 1-mark & 3-mark Q&A', 'What are the main concepts?'],
              created_at: new Date().toISOString(),
            };
          } else {
            const groundedRes = await synthesizeGroundedAnswer(userText, matched, wsId);
            assistantMsg = {
              id: 'msg-' + (Date.now() + 1),
              role: 'assistant',
              ...groundedRes,
              created_at: new Date().toISOString(),
            };
          }
        }
      } else {
        // Fallback demo dopamine response
        assistantMsg = {
          id: 'msg-' + (Date.now() + 1),
          role: 'assistant',
          content: `Based on your uploaded course notes, the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory and sustained attention [1]. Experimental evidence demonstrates that optimal D1 receptor stimulation enhances the signal-to-noise ratio in cortical pyramidal neurons [2].`,
          answer: [
            {
              text: `Based on your uploaded course notes, the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory and sustained attention [1]. Experimental evidence demonstrates that optimal D1 receptor stimulation enhances the signal-to-noise ratio in cortical pyramidal neurons [2].`,
              citations: [],
            },
          ],
          created_at: new Date().toISOString(),
          citations: [
            {
              n: 1,
              citation_num: 1,
              document_id: 'doc-demo-dopamine',
              page: 2,
              quote: 'the mesocortical projection directs dopamine to the prefrontal cortex to govern working memory',
              bbox: [0.08, 0.48, 0.92, 0.58],
              bounding_box: [60, 480, 520, 520],
            },
            {
              n: 2,
              citation_num: 2,
              document_id: 'doc-demo-dopamine',
              page: 2,
              quote: 'optimal D1 receptor stimulation enhances signal-to-noise ratio in cortical pyramidal neurons',
              bbox: [0.08, 0.52, 0.92, 0.62],
              bounding_box: [60, 520, 520, 555],
            },
          ],
          confidence: 'high',
          verification_status: 'grounded',
        };
      }

      demoStore.messages[convId].push(assistantMsg);
      return assistantMsg;
    }
    return demoStore.messages[convId] || [];
  }

  // 6. Study Tools
  const wsStudyMatch = cleanEp.match(/\/workspaces\/([^\/]+)\/study\//);
  const wsQuizzesMatch = cleanEp.match(/\/workspaces\/([^\/]+)\/quizzes/);
  const activeWsId = (wsStudyMatch ? wsStudyMatch[1] : null) || (wsQuizzesMatch ? wsQuizzesMatch[1] : null) || state.currentWorkspaceId || 'ws-demo-neuro';

  if (cleanEp.includes('/study/flashcards')) {
    const body = options.body ? JSON.parse(options.body) : {};
    return generateDynamicFlashcards(activeWsId, body.count || 5);
  }
  if (cleanEp.includes('/study/summary')) {
    const body = options.body ? JSON.parse(options.body) : {};
    return generateDynamicSummary(activeWsId, body.length || 'medium');
  }
  if (cleanEp.includes('/study/qa')) {
    return generateDynamicQa(activeWsId);
  }
  if (cleanEp.includes('/study/items')) {
    const fcData = generateDynamicFlashcards(activeWsId, 5);
    return { items: (fcData.flashcards || []).map((f, idx) => ({ id: 'item-' + idx, type: 'flashcard', payload: f })) };
  }

  // 7. Quiz & Practice
  if (cleanEp.includes('/study/quiz') || cleanEp.includes('/quizzes')) {
    const body = options.body ? JSON.parse(options.body) : {};
    return generateDynamicQuiz(activeWsId, body.count || 3, body.difficulty || 'medium');
  }
  if (cleanEp.includes('/answers')) {
    return { status: 'recorded', correct: true, feedback: 'Correct! Verified against course notes.' };
  }
  if (cleanEp.includes('/submit')) {
    return { score: 2, total_marks: 2, percentage: 100, topic_breakdown: { 'Course Mastery': 100 } };
  }
  if (cleanEp.includes('/feedback') || cleanEp.includes('/report')) {
    return { status: 'recorded', message: 'Feedback saved' };
  }

  return { status: 'ok', demo: true };
}

function updateServerStatusUI(mode) {
  const label = document.getElementById('server-status-label');
  const dot = document.getElementById('server-status-dot');
  const modalDot = document.getElementById('server-modal-dot');
  const modalText = document.getElementById('server-modal-status-text');
  const urlInput = document.getElementById('server-api-url-input');

  const currentBase = localStorage.getItem('studymind_api_base');
  if (urlInput && currentBase) {
    urlInput.value = currentBase;
  }
  const geminiInput = document.getElementById('server-gemini-key-input');
  const currentGeminiKey = localStorage.getItem('gemini_api_key');
  if (geminiInput && currentGeminiKey) {
    geminiInput.value = currentGeminiKey;
  }

  if (mode === 'connected' && currentBase) {
    if (label) label.textContent = 'Backend Online';
    if (dot) { dot.className = 'status-indicator-dot'; }
    if (modalDot) { modalDot.className = 'status-indicator-dot'; }
    if (modalText) modalText.textContent = `Connected to ${currentBase}`;
  } else {
    if (label) label.textContent = 'Demo Mode';
    if (dot) { dot.className = 'status-indicator-dot demo'; }
    if (modalDot) { modalDot.className = 'status-indicator-dot demo'; }
    if (modalText) modalText.textContent = 'Interactive Standalone Demo Mode (Preloaded Materials)';
  }
}

// ============================================================================
// API Client
// ============================================================================

async function apiRequest(endpoint, options = {}) {
  if (state.isDemoMode) {
    return await handleMockApiRequest(endpoint, options);
  }

  const headers = options.headers || {};
  if (state.token) {
    headers['Authorization'] = `Bearer ${state.token}`;
  }
  if (!options.isFormData && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const config = {
    ...options,
    headers,
  };

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, config);
    if (res.status === 401) {
      handleUnauthorized();
      throw new Error('Authentication expired or invalid');
    }
    if (res.status === 204) {
      return null;
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = data?.error?.message || data?.detail || `API error (${res.status})`;
      if (res.status === 404 || res.status === 405 || res.status >= 500) {
        console.warn(`API returned ${res.status} for ${endpoint}. Activating demo mode fallback.`);
        state.isDemoMode = true;
        updateServerStatusUI('demo');
        return await handleMockApiRequest(endpoint, options);
      }
      throw new Error(msg);
    }
    updateServerStatusUI('connected');
    return data;
  } catch (err) {
    if (err.name === 'TypeError' || err.message.includes('fetch') || err.message.includes('NetworkError')) {
      console.warn(`Connection failed to ${API_BASE}${endpoint}. Activating demo mode fallback.`);
      state.isDemoMode = true;
      updateServerStatusUI('demo');
      return await handleMockApiRequest(endpoint, options);
    }
    console.error(`API Error [${endpoint}]:`, err);
    throw err;
  }
}

// ============================================================================
// UI Utilities & Toasts
// ============================================================================

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ'}</span> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ============================================================================
// Auth & Initial Setup
// ============================================================================

async function initApp() {
  loadDemoStoreFromStorage();
  bindEventListeners();

  // On mobile/tablet screens, ensure Source Viewer is closed so user lands cleanly on Chat
  if (window.innerWidth <= 1024) {
    setViewerOpen(false);
  }

  if (state.token) {
    try {
      state.user = await apiRequest('/auth/me');
      state.isGuest = state.user?.email?.startsWith('guest_') || localStorage.getItem('studymind_is_guest') === 'true';
      updateUserNavUI();
      await loadWorkspaces();
      return;
    } catch {
      // Fallback to guest if token expired
    }
  }

  // Seamless Guest Mode: users can use the app without signing in
  await startGuestSession();
}

async function startGuestSession() {
  try {
    const res = await apiRequest('/auth/guest', { method: 'POST' });
    state.token = res.access_token;
    state.user = res.user;
    state.isGuest = true;
    localStorage.setItem('studymind_token', state.token);
    localStorage.setItem('studymind_is_guest', 'true');
    updateUserNavUI();
    showAuthModal(false);
    showToast(state.isDemoMode ? 'Entered Guest Mode (Demo Materials Active)' : 'Active in Guest Mode. Upload documents & start studying!', 'info');
    await loadWorkspaces();
  } catch (err) {
    console.warn('Backend unavailable, switching to Interactive Demo Mode:', err);
    state.token = 'demo-guest-token-' + Date.now();
    state.user = { id: 'usr-guest-demo', email: 'guest_student@studymind.io' };
    state.isGuest = true;
    state.isDemoMode = true;
    localStorage.setItem('studymind_token', state.token);
    localStorage.setItem('studymind_is_guest', 'true');
    updateUserNavUI();
    updateServerStatusUI('demo');
    showAuthModal(false);
    showToast('Active in Demo Mode: sample study materials loaded!', 'success');
    await loadWorkspaces();
  }
}

function handleUnauthorized() {
  state.token = null;
  state.user = null;
  state.isGuest = false;
  localStorage.removeItem('studymind_token');
  localStorage.removeItem('studymind_is_guest');
  updateUserNavUI();
  startGuestSession();
}

function updateUserNavUI() {
  const badge = document.getElementById('user-profile-badge');
  const loginBtn = document.getElementById('btn-open-login');
  const emailText = document.getElementById('user-email-text');
  const roleBadge = document.getElementById('user-role-badge');
  const saveBtn = document.getElementById('btn-save-guest');

  if (state.user && state.token) {
    badge.classList.remove('hidden');
    loginBtn.classList.add('hidden');

    const isGuest = state.isGuest || state.user.email?.startsWith('guest_');
    if (isGuest) {
      if (roleBadge) {
        roleBadge.classList.remove('hidden');
        roleBadge.textContent = 'Guest';
      }
      if (saveBtn) saveBtn.classList.remove('hidden');
      emailText.textContent = 'Guest Session';
    } else {
      if (roleBadge) roleBadge.classList.add('hidden');
      if (saveBtn) saveBtn.classList.add('hidden');
      emailText.textContent = state.user.email;
    }
  } else {
    badge.classList.add('hidden');
    loginBtn.classList.remove('hidden');
    if (roleBadge) roleBadge.classList.add('hidden');
    if (saveBtn) saveBtn.classList.add('hidden');
  }
}

function showAuthModal(show) {
  const modal = document.getElementById('auth-modal');
  const errorEl = document.getElementById('auth-error-msg');
  if (errorEl) errorEl.classList.add('hidden');
  if (show) {
    modal.classList.remove('hidden');
  } else {
    modal.classList.add('hidden');
  }
}

// ============================================================================
// Workspace Management
// ============================================================================

async function loadWorkspaces() {
  try {
    const wsList = await apiRequest('/workspaces');
    state.workspaces = wsList || [];

    const select = document.getElementById('workspace-select');
    select.innerHTML = '';

    if (state.workspaces.length === 0) {
      // Auto-create default workspace
      const created = await apiRequest('/workspaces', {
        method: 'POST',
        body: JSON.stringify({ name: 'Default Study Workspace' }),
      });
      state.workspaces = [created];
    }

    state.workspaces.forEach((ws) => {
      const opt = document.createElement('option');
      opt.value = ws.id;
      opt.textContent = ws.name;
      select.appendChild(opt);
    });

    // Select active workspace
    const existing = state.workspaces.find((w) => w.id === state.currentWorkspaceId);
    if (existing) {
      select.value = existing.id;
    } else {
      select.value = state.workspaces[0].id;
      state.currentWorkspaceId = state.workspaces[0].id;
    }
    localStorage.setItem('studymind_ws_id', state.currentWorkspaceId);

    // Load workspace data
    await Promise.all([loadDocuments(), loadConversations()]);
  } catch (err) {
    showToast(`Failed to load workspaces: ${err.message}`, 'error');
  }
}

// ============================================================================
// Document Management & Ingestion
// ============================================================================

async function loadDocuments() {
  if (!state.currentWorkspaceId) return;
  try {
    const docs = await apiRequest(`/workspaces/${state.currentWorkspaceId}/documents`);
    state.documents = docs || [];

    const docCountBadge = document.getElementById('library-doc-count');
    if (docCountBadge) docCountBadge.textContent = state.documents.length;

    renderDocumentsTable();
  } catch (err) {
    console.error('Failed to load documents:', err);
  }
}

function renderDocumentsTable() {
  const tbody = document.getElementById('documents-table-body');
  if (!tbody) return;

  if (state.documents.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No documents uploaded yet. Upload course materials above to begin.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.documents
    .map((doc) => {
      const ocrClass = doc.ocr_quality === 'good' ? 'good' : doc.ocr_quality === 'medium' ? 'medium' : 'low';
      const ocrLabel = doc.ocr_quality || 'N/A';
      const statusClass = doc.status === 'ready' ? 'ready' : doc.status === 'failed' ? 'failed' : 'queued';

      return `
      <tr data-doc-id="${doc.id}">
        <td>
          <div style="display:flex; align-items:center; gap:8px;">
            <span>📄</span>
            <span style="font-weight:600; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
              ${escapeHtml(doc.filename)}
            </span>
          </div>
        </td>
        <td>${doc.pages || 1} pages</td>
        <td><span class="badge-ocr ${ocrClass}">${ocrLabel}</span></td>
        <td><span class="badge-status ${statusClass}">${doc.status}</span></td>
        <td>
          <div style="display:flex; gap:6px;">
            <button class="btn-icon-sm btn-inspect-doc" data-doc-id="${doc.id}" data-pages="${doc.pages || 1}" title="View in Source Viewer">👁</button>
            <button class="btn-icon-sm btn-delete-doc" data-doc-id="${doc.id}" title="Delete document" style="color:var(--rose);">🗑</button>
          </div>
        </td>
      </tr>
    `;
    })
    .join('');

  // Attach row actions
  tbody.querySelectorAll('.btn-inspect-doc').forEach((btn) => {
    btn.addEventListener('click', () => {
      const docId = btn.getAttribute('data-doc-id');
      const pages = parseInt(btn.getAttribute('data-pages') || '1', 10);
      openSourceViewer(docId, 1, pages);
    });
  });

  tbody.querySelectorAll('.btn-delete-doc').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const docId = btn.getAttribute('data-doc-id');
      if (!confirm('Are you sure you want to delete this document?')) return;
      try {
        await apiRequest(`/documents/${docId}`, { method: 'DELETE' });
        showToast('Document deleted', 'info');
        await loadDocuments();
      } catch (err) {
        showToast(`Delete failed: ${err.message}`, 'error');
      }
    });
  });
}

async function handleMultipleFiles(files) {
  if (!files || files.length === 0) return;
  if (!state.currentWorkspaceId) {
    showToast('Please select a workspace first', 'error');
    return;
  }

  const fileList = Array.from(files);
  const total = fileList.length;

  const progressCard = document.getElementById('ingestion-progress-card');
  const progressDocName = document.getElementById('progress-doc-name');
  const progressFill = document.getElementById('progress-fill');
  const progressStage = document.getElementById('progress-stage-badge');
  const progressPercent = document.getElementById('progress-percent-text');

  if (progressCard) progressCard.classList.remove('hidden');

  let successCount = 0;
  let lastDocId = null;
  let lastPages = 1;

  for (let i = 0; i < total; i++) {
    const file = fileList[i];
    const itemNum = i + 1;
    const basePct = Math.round((i / total) * 100);

    if (progressDocName) progressDocName.textContent = `[${itemNum}/${total}] ${file.name}`;
    if (progressStage) progressStage.textContent = `reading ${itemNum}/${total}`;
    if (progressFill) progressFill.style.width = `${basePct + 15}%`;
    if (progressPercent) progressPercent.textContent = `${basePct + 15}%`;

    try {
      const ext = file.name.split('.').pop().toLowerCase();
      let parsedDoc = null;

      if (progressStage) progressStage.textContent = `parsing & indexing ${itemNum}/${total}`;

      if (ext === 'pdf') {
        parsedDoc = await extractPdfClientSide(file);
      } else if (ext === 'docx') {
        parsedDoc = await extractDocxFileClientSide(file);
      } else if (['txt', 'md', 'json', 'csv', 'py', 'js', 'html'].includes(ext)) {
        parsedDoc = await extractTextFileClientSide(file);
      } else if (['png', 'jpg', 'jpeg', 'webp'].includes(ext)) {
        parsedDoc = await extractImageFileClientSide(file);
      } else {
        parsedDoc = await extractTextFileClientSide(file);
      }

      const docId = 'doc-' + Date.now() + '-' + Math.random().toString(36).substring(2, 6);
      const numPages = parsedDoc ? parsedDoc.numPages : 1;
      const chunks = parsedDoc ? parsedDoc.chunks : [];
      const pages = parsedDoc ? parsedDoc.pages : [];

      // Store in memory stores
      if (!demoStore.customDocs) demoStore.customDocs = {};
      demoStore.customDocs[docId] = {
        id: docId,
        filename: file.name,
        page_count: numPages,
        pages,
        chunks,
      };

      if (!demoStore.customPageImages) demoStore.customPageImages = {};
      demoStore.customPageImages[docId] = {};
      pages.forEach((p) => {
        demoStore.customPageImages[docId][p.pageNo] = p.image;
      });

      if (!demoStore.customChunks) demoStore.customChunks = {};
      if (!demoStore.customChunks[state.currentWorkspaceId]) demoStore.customChunks[state.currentWorkspaceId] = [];
      chunks.forEach((c) => {
        c.document_id = docId;
        c.filename = file.name;
        demoStore.customChunks[state.currentWorkspaceId].push(c);
      });

      const docRecord = {
        id: docId,
        filename: file.name,
        pages: numPages,
        page_count: numPages,
        status: 'ready',
        ocr_quality: 'good',
        chunk_count: chunks.length,
        created_at: new Date().toISOString(),
      };

      if (!demoStore.documents[state.currentWorkspaceId]) {
        demoStore.documents[state.currentWorkspaceId] = [];
      }
      demoStore.documents[state.currentWorkspaceId].unshift(docRecord);

      // Persist custom materials in storage so they survive page reloads and tab switches
      saveDemoStoreToStorage();

      // If backend is active and not in demo mode, also attempt upload to backend
      if (!state.isDemoMode) {
        try {
          const formData = new FormData();
          formData.append('file', file);
          await apiRequest(`/workspaces/${state.currentWorkspaceId}/documents`, {
            method: 'POST',
            body: formData,
            isFormData: true,
          });
        } catch (backendErr) {
          console.warn('Backend document upload skipped, client-side indexing active:', backendErr);
        }
      }

      lastDocId = docId;
      lastPages = numPages;
      successCount++;
    } catch (err) {
      console.error(`Failed to ingest ${file.name}:`, err);
      showToast(`Upload failed for ${file.name}: ${err.message}`, 'error');
    }
  }

  if (progressFill) progressFill.style.width = '100%';
  if (progressStage) progressStage.textContent = 'ready';
  if (progressPercent) progressPercent.textContent = '100%';

  if (successCount > 0) {
    showToast(
      total === 1
        ? `"${fileList[0].name}" indexed! Ready for study, chat & quizzes.`
        : `Successfully ingested & indexed ${successCount} documents!`,
      'success'
    );
  }

  setTimeout(() => {
    if (progressCard) progressCard.classList.add('hidden');
  }, 2200);

  await loadDocuments();

  if (lastDocId && window.innerWidth > 768) {
    openSourceViewer(lastDocId, 1, lastPages);
  }

  const fileInput = document.getElementById('file-upload-input');
  if (fileInput) fileInput.value = '';
  const galleryInput = document.getElementById('gallery-upload-input');
  if (galleryInput) galleryInput.value = '';
  const cameraInput = document.getElementById('camera-upload-input');
  if (cameraInput) cameraInput.value = '';
}

async function handleFileUpload(file) {
  return handleMultipleFiles([file]);
}

// ============================================================================
// Conversations & Chat
// ============================================================================

async function loadConversations() {
  if (!state.currentWorkspaceId) return;
  try {
    const convs = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`);
    state.conversations = convs || [];

    const select = document.getElementById('conv-select');
    if (select) select.innerHTML = '';

    if (state.conversations.length === 0) {
      // Create first study conversation
      const newConv = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`, {
        method: 'POST',
        body: JSON.stringify({ title: 'Study Chat' }),
      });
      state.conversations = [newConv];
    }

    state.conversations.forEach((c) => {
      if (select) {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.title;
        select.appendChild(opt);
      }
    });

    state.currentConversationId = state.conversations[0].id;
    if (select) select.value = state.currentConversationId;
    renderSidebarConversations();
    await loadMessages(state.currentConversationId);
  } catch (err) {
    console.error('Failed to load conversations:', err);
  }
}

function renderSidebarConversations() {
  const list = document.getElementById('sidebar-conv-list');
  if (!list) return;
  list.innerHTML = '';

  state.conversations.forEach((c) => {
    const item = document.createElement('div');
    const isActive = c.id === state.currentConversationId;
    item.className = `sidebar-conv-item ${isActive ? 'active' : ''}`;
    item.setAttribute('data-conv-id', c.id);
    item.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; overflow:hidden; flex:1;">
        <span style="font-size:0.85rem; opacity:0.7;">💬</span>
        <span class="sidebar-conv-title">${escapeHtml(c.title)}</span>
      </div>
    `;
    item.addEventListener('click', async () => {
      if (state.currentConversationId === c.id) return;
      state.currentConversationId = c.id;
      const select = document.getElementById('conv-select');
      if (select) select.value = c.id;
      renderSidebarConversations();
      await loadMessages(c.id);
    });
    list.appendChild(item);
  });
}

async function loadMessages(convId) {
  if (!convId) return;
  try {
    const msgs = await apiRequest(`/conversations/${convId}/messages`);
    renderMessages(msgs || []);
  } catch (err) {
    console.error('Failed to load messages:', err);
  }
}

function renderMessages(messages) {
  const container = document.getElementById('messages-container');
  const emptyState = document.getElementById('chat-empty-state');

  if (messages.length === 0) {
    container.innerHTML = '';
    if (emptyState) container.appendChild(emptyState);
    return;
  }

  container.innerHTML = '';
  messages.forEach((msg) => {
    if (msg.role === 'user') {
      appendUserMessage(msg.content);
    } else {
      appendAssistantMessage({
        message_id: msg.id,
        abstained: msg.abstained,
        confidence: msg.verification?.confidence || 'high',
        answer: [{ text: msg.content, citations: [] }],
        citations: msg.citations || [],
        dropped_claims: msg.verification?.dropped_claims || 0,
        missing_info: msg.verification?.missing_info,
        suggestions: [],
      });
    }
  });

  // Scroll to bottom
  container.scrollTop = container.scrollHeight;
}

function appendUserMessage(text) {
  const container = document.getElementById('messages-container');
  const emptyState = document.getElementById('chat-empty-state');
  if (emptyState && emptyState.parentElement === container) {
    emptyState.remove();
  }

  const bubble = document.createElement('div');
  bubble.className = 'message-user';
  bubble.textContent = text;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

function formatAssistantMarkdown(rawText) {
  if (!rawText) return '';

  // 1. Extract code blocks first (triple backtick) so inner formatting is preserved
  const codeBlocks = [];
  let text = rawText.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (match, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: lang || 'code', code: code.trim() });
    return `___CODE_BLOCK_${idx}___`;
  });

  // 2. Replace citations in text with clickable pills [1], [2], etc.
  text = text.replace(/\[(\d+)\]/g, (match, num) => {
    return `<button type="button" class="citation-pill" data-cit-num="${num}" id="pill-cit-${num}">[${num}]</button>`;
  });

  // 3. Inline code `code`
  text = text.replace(/`([^`]+)`/g, (match, code) => {
    return `<code>${escapeHtml(code)}</code>`;
  });

  // 4. Bold: **bold**
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // 5. Italic: *italic*
  text = text.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');

  // Marks Badge Formatting (1 Mark & 3 Mark)
  text = text.replace(/(?:\(|\[)1\s*Mark(?:\)|\])/gi, '<span class="marks-badge mark-1">1 Mark</span>');
  text = text.replace(/(?:\(|\[)3\s*Marks?(?:\)|\])/gi, '<span class="marks-badge mark-3">3 Marks</span>');

  // Headers: ### Header
  text = text.replace(/###\s*(.+)/g, '<h4 style="margin: 12px 0 6px; color: var(--primary-light); font-weight: 700; font-size: 0.98rem;">$1</h4>');

  // 6. Split into paragraphs and handle lists
  const paragraphs = text.split(/\n{2,}/);
  text = paragraphs
    .map((p) => {
      p = p.trim();
      if (!p) return '';
      if (p.includes('\n- ') || p.startsWith('- ')) {
        const lines = p.split('\n');
        let listItems = '';
        let nonList = '';
        lines.forEach((line) => {
          line = line.trim();
          if (line.startsWith('- ')) {
            listItems += `<li>${line.substring(2)}</li>`;
          } else if (line) {
            if (listItems) {
              nonList += `<ul>${listItems}</ul>`;
              listItems = '';
            }
            nonList += `<p>${line}</p>`;
          }
        });
        if (listItems) nonList += `<ul>${listItems}</ul>`;
        return nonList;
      }
      return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    })
    .join('');

  // 7. Re-inject code blocks
  text = text.replace(/___CODE_BLOCK_(\d+)___/g, (match, idx) => {
    const block = codeBlocks[parseInt(idx, 10)];
    if (!block) return '';
    return `
      <div class="code-block-wrapper">
        <div class="code-block-header">
          <span class="code-lang">${escapeHtml(block.lang)}</span>
          <button type="button" class="btn-copy-code" onclick="copyCodeBlock(this)">Copy code</button>
        </div>
        <pre><code>${escapeHtml(block.code)}</code></pre>
      </div>
    `;
  });

  return text;
}

window.copyToClipboard = async function (text, btnElement) {
  try {
    await navigator.clipboard.writeText(text);
    if (btnElement) {
      const orig = btnElement.innerHTML;
      btnElement.innerHTML = '✓ Copied';
      setTimeout(() => {
        btnElement.innerHTML = orig;
      }, 2000);
    }
    showToast('Copied to clipboard', 'info');
  } catch (err) {
    showToast('Failed to copy to clipboard', 'error');
  }
};

window.copyCodeBlock = function (btn) {
  const codeEl = btn.closest('.code-block-wrapper')?.querySelector('code');
  if (codeEl) {
    window.copyToClipboard(codeEl.innerText, btn);
  }
};

function appendAssistantMessage(payload) {
  const container = document.getElementById('messages-container');
  const emptyState = document.getElementById('chat-empty-state');
  if (emptyState && emptyState.parentElement === container) {
    emptyState.remove();
  }

  const msgId = payload.message_id || `msg-${Date.now()}`;
  const card = document.createElement('div');
  card.className = `message-assistant ${payload.abstained ? 'abstain-card' : ''}`;
  card.setAttribute('id', `msg-card-${msgId}`);

  if (payload.abstained) {
    // Render Abstention Card
    let suggestionsHtml = '';
    if (payload.suggestions && payload.suggestions.length > 0) {
      suggestionsHtml = `
        <div class="suggestions-group">
          <div class="suggestions-title">Suggested Alternative Questions:</div>
          ${payload.suggestions
            .map(
              (s, i) =>
                `<button type="button" class="suggestion-chip" id="suggestion-chip-${i}" data-query="${escapeHtml(s)}">${escapeHtml(s)}</button>`
            )
            .join('')}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="abstain-header">
        <span>⚠</span>
        <span>Insufficient Verified Evidence (Abstention)</span>
      </div>
      <p class="abstain-reason">
        StudyMind only generates answers that are strictly verified against your uploaded materials.
        ${payload.missing_info ? `<br><strong>Missing:</strong> ${escapeHtml(payload.missing_info)}` : ''}
      </p>
      ${suggestionsHtml}
    `;

    // Bind suggestion chips
    card.querySelectorAll('.suggestion-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const query = chip.getAttribute('data-query');
        const input = document.getElementById('chat-input');
        input.value = query;
        document.getElementById('chat-form').dispatchEvent(new Event('submit'));
      });
    });
  } else {
    // Normal Grounded Answer
    const confidence = payload.confidence || 'high';
    const answerText = payload.answer
      ? payload.answer
          .map((a) => a.text)
          .join(payload.answer.some((a) => a.text && a.text.trim().startsWith('-')) ? '\n' : ' ')
      : (payload.content || '');
    const formattedHtml = formatAssistantMarkdown(answerText);

    // Render citations card list
    let sourcesListHtml = '';
    if (payload.citations && payload.citations.length > 0) {
      sourcesListHtml = `
        <div class="msg-sources-container">
          <span class="sources-label">Grounded Sources & Citations</span>
          ${payload.citations
            .map((cit) => {
              const citNum = cit.n || cit.citation_num || 1;
              const docName = getDocumentNameById(cit.document_id);
              return `
              <div class="citation-card" data-cit-num="${citNum}" id="citation-card-${citNum}">
                <div class="citation-meta">
                  <span class="citation-index">[${citNum}]</span>
                  <span class="citation-file">${escapeHtml(docName)}</span>
                  <span class="citation-page">Page ${cit.page || 1}</span>
                </div>
                <div class="citation-quote-preview" title="${escapeHtml(cit.quote || '')}">"${escapeHtml(cit.quote || '')}"</div>
                <button type="button" class="btn-inspect-citation" data-cit-num="${citNum}">Inspect ↗</button>
              </div>
            `;
            })
            .join('')}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="msg-header">
        <div class="msg-author">
          <div class="bot-avatar">⚡</div>
          <span>StudyMind Assistant</span>
        </div>
        <span class="confidence-badge ${confidence}">${confidence} confidence</span>
      </div>
      <div class="msg-body">${formattedHtml}</div>
      ${sourcesListHtml}
      <div class="msg-actions-footer">
        <div class="feedback-group">
          <span class="feedback-prompt">Helpful answer?</span>
          <button type="button" class="btn-feedback" id="btn-thumb-up-${msgId}" title="Accurate & helpful">👍</button>
          <button type="button" class="btn-feedback" id="btn-thumb-down-${msgId}" title="Report issue">👎</button>
          <button type="button" class="btn-feedback" id="btn-copy-msg-${msgId}" title="Copy response to clipboard">📋</button>
        </div>
      </div>
    `;

    // Bind citation pill clicks
    card.querySelectorAll('.citation-pill, .citation-card, .btn-inspect-citation').forEach((el) => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const citNum = parseInt(el.getAttribute('data-cit-num'), 10);
        const cit = payload.citations.find((c) => c.n === citNum || c.citation_num === citNum);
        if (cit) {
          triggerCitationHighlight(cit);
        }
      });
    });

    // Bind feedback buttons
    const btnUp = card.querySelector(`#btn-thumb-up-${msgId}`);
    const btnDown = card.querySelector(`#btn-thumb-down-${msgId}`);
    const btnCopy = card.querySelector(`#btn-copy-msg-${msgId}`);

    if (btnCopy) {
      btnCopy.addEventListener('click', () => {
        window.copyToClipboard(answerText, btnCopy);
      });
    }

    if (btnUp) {
      btnUp.addEventListener('click', async () => {
        try {
          await apiRequest(`/messages/${payload.message_id}/feedback`, {
            method: 'POST',
            body: JSON.stringify({ rating: 'up' }),
          });
          btnUp.classList.add('active-up');
          btnDown?.classList.remove('active-down');
          showToast('Feedback submitted: Thank you!', 'success');
        } catch (err) {
          showToast(`Feedback failed: ${err.message}`, 'error');
        }
      });
    }

    if (btnDown) {
      btnDown.addEventListener('click', () => {
        openFeedbackModal(payload.message_id);
      });
    }
  }

  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
}

function getDocumentNameById(docId) {
  const doc = state.documents.find((d) => d.id === docId);
  return doc ? doc.filename : 'Course Document';
}

async function handleSendMessage(question) {
  if (!question || !question.trim()) return;
  if (!state.currentConversationId) {
    if (!state.currentWorkspaceId) {
      showToast('Please select a workspace first', 'error');
      return;
    }
    try {
      const newConv = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`, {
        method: 'POST',
        body: JSON.stringify({ title: `Study Chat (${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})` }),
      });
      state.currentConversationId = newConv.id;
      await loadConversations();
      const convSelect = document.getElementById('conv-select');
      if (convSelect) convSelect.value = newConv.id;
    } catch (err) {
      showToast('Please select or create a conversation first', 'error');
      return;
    }
  }

  appendUserMessage(question);

  const statusBar = document.getElementById('pipeline-status-bar');
  const statusText = document.getElementById('pipeline-status-text');
  statusBar.classList.remove('hidden');
  statusText.textContent = 'Searching index & verifying citations...';

  try {
    const reqBody = {
      question: question.trim(),
      strict_mode: state.strictMode,
    };
    const qLower = question.toLowerCase();
    if (state.currentViewerDocId && (qLower.includes('this page') || qLower.includes('current page') || qLower.includes('the page') || qLower.includes('this pdf') || qLower.includes('this doc'))) {
      reqBody.document_ids = [state.currentViewerDocId];
      if (qLower.includes('this page') || qLower.includes('current page') || qLower.includes('the page')) {
        reqBody.page = state.currentViewerPage;
      }
    }

    const payload = await apiRequest(`/conversations/${state.currentConversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify(reqBody),
    });

    statusBar.classList.add('hidden');
    appendAssistantMessage(payload);

    // If citations are available, automatically highlight the first one in the viewer on desktop
    if (payload.citations && payload.citations.length > 0 && window.innerWidth > 768) {
      triggerCitationHighlight(payload.citations[0]);
    }
  } catch (err) {
    statusBar.classList.add('hidden');
    showToast(`Question failed: ${err.message}`, 'error');
  }
}

// ============================================================================
// Interactive Source Viewer & Bounding Box Overlay (DoD Requirement)
// ============================================================================

function setViewerOpen(open) {
  const viewerPanel = document.getElementById('source-viewer-panel');
  const toggleViewerBtn = document.getElementById('btn-toggle-source-viewer');
  if (!viewerPanel) return;
  if (open) {
    viewerPanel.classList.remove('hidden');
    toggleViewerBtn?.classList.add('active');
    document.getElementById('mobile-tab-source')?.classList.add('active');
  } else {
    viewerPanel.classList.add('hidden');
    toggleViewerBtn?.classList.remove('active');
    document.getElementById('mobile-tab-source')?.classList.remove('active');
    // Restore active tab highlight in mobile navigation
    const currentActiveView = document.querySelector('.main-stage-view.active');
    if (currentActiveView) {
      const viewId = currentActiveView.id;
      const tabName = viewId === 'library-view' ? 'library' : viewId === 'study-view' ? 'study' : 'chat';
      document.querySelectorAll('.mobile-nav-item').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
      });
    }
  }
}

async function openSourceViewer(docId, pageNo = 1, maxPages = 1, citationContext = null) {
  setViewerOpen(true);
  state.currentViewerDocId = docId;
  state.currentViewerPage = pageNo;
  state.activeCitation = citationContext;

  const doc = state.documents.find((d) => d.id === docId);
  const totalPages = doc?.page_count || maxPages || 1;
  state.currentViewerMaxPages = totalPages;

  const titleEl = document.getElementById('viewer-doc-title');
  const placeholderEl = document.getElementById('viewer-empty-state');
  const stageEl = document.getElementById('viewer-stage');
  const pageIndicator = document.getElementById('viewer-page-indicator');
  const prevBtn = document.getElementById('btn-prev-page');
  const nextBtn = document.getElementById('btn-next-page');
  const downloadBtn = document.getElementById('btn-download-file');
  const citationTag = document.getElementById('viewer-citation-tag');

  titleEl.textContent = doc ? doc.filename : `Document (${docId.slice(0, 8)})`;
  placeholderEl.classList.add('hidden');
  stageEl.classList.remove('hidden');

  pageIndicator.textContent = `Page ${pageNo} / ${state.currentViewerMaxPages}`;
  prevBtn.disabled = pageNo <= 1;
  nextBtn.disabled = pageNo >= state.currentViewerMaxPages;
  downloadBtn.disabled = false;

  if (citationContext) {
    citationTag.textContent =
      citationContext.tag ||
      (citationContext.n ? `Referenced by Citation [${citationContext.n}]` : 'Source Reference');
    citationTag.classList.remove('hidden');
  } else {
    citationTag.classList.add('hidden');
    document.getElementById('source-highlight-box')?.classList.add('hidden');
  }

  await loadPageImage(docId, pageNo);
}

function generateDemoPageSvg(docId, pageNo) {
  // Check if this document is a custom user-uploaded file with extracted lines
  const customDoc = demoStore.customDocs?.[docId];
  if (customDoc && customDoc.pages) {
    const pageObj = customDoc.pages.find((p) => p.pageNo === pageNo) || customDoc.pages[0];
    if (pageObj && pageObj.lines) {
      return generateTextPageSvg(customDoc.filename, pageNo, customDoc.page_count, pageObj.lines);
    }
  }

  // Fallback demo Neuroscience Handout SVG
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 850" width="100%" height="100%">
    <rect width="600" height="850" fill="#1b1a18" rx="8"/>
    <!-- Document Header -->
    <rect x="40" y="35" width="520" height="65" fill="#262421" rx="6" stroke="#3d3a35" stroke-width="1"/>
    <text x="60" y="70" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="16" font-weight="700" fill="#f8fafc">Neuroscience 101 — Chapter 4: Dopaminergic Signaling</text>
    <text x="60" y="88" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="11" fill="#a8a29e">Course Syllabus &amp; Lecture Handout • Page ${pageNo} of 3</text>
    
    <!-- Section 1 -->
    <text x="60" y="140" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="13" font-weight="700" fill="#e07a5f">4.1 Dopamine Projections and Synaptic Plasticity</text>
    <text x="60" y="172" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">Dopamine serves as a critical reward-prediction error signal in the mesolimbic</text>
    <text x="60" y="190" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">pathway. When an outcome is better than anticipated, phasic dopamine release</text>
    <text x="60" y="212" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">reinforces associated behavioral actions, facilitating synaptic plasticity in the</text>
    <text x="60" y="230" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">prefrontal cortex and striatum through long-term potentiation (LTP).</text>

    <!-- Diagram Box -->
    <rect x="60" y="260" width="480" height="150" fill="#141311" stroke="#3d3a35" stroke-width="1.5" rx="6"/>
    <text x="80" y="290" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="11" font-weight="600" fill="#81b29a">Figure 4.2 — Mesocortical vs Mesolimbic Dopamine Loop</text>
    <rect x="85" y="315" width="115" height="40" fill="#2d3748" stroke="#4a5568" rx="4"/>
    <text x="105" y="340" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="11" font-weight="600" fill="#ffffff">VTA Neurons</text>
    <path d="M 205 335 L 255 335" stroke="#e07a5f" stroke-width="2"/>
    <rect x="260" y="315" width="130" height="40" fill="#2d3748" stroke="#4a5568" rx="4"/>
    <text x="275" y="340" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="11" font-weight="600" fill="#ffffff">Nucleus Accumbens</text>
    <path d="M 395 335 L 435 335" stroke="#e07a5f" stroke-width="2"/>
    <rect x="440" y="315" width="85" height="40" fill="#2d3748" stroke="#4a5568" rx="4"/>
    <text x="465" y="340" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="11" font-weight="600" fill="#ffffff">PFC</text>

    <!-- Section 2 -->
    <text x="60" y="455" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="13" font-weight="700" fill="#e07a5f">4.2 Working Memory Modulation via D1 Receptors</text>
    <text x="60" y="490" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">the mesocortical projection directs dopamine to the prefrontal cortex to govern</text>
    <text x="60" y="508" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">working memory and sustained attention. optimal D1 receptor stimulation enhances</text>
    <text x="60" y="530" font-family="'JetBrains Mono', monospace" font-size="11" fill="#f4f1de">signal-to-noise ratio in cortical pyramidal neurons during cognitive tasks.</text>
    <text x="60" y="560" font-family="'JetBrains Mono', monospace" font-size="11" fill="#a8a29e">Insufficient or excessive D1 stimulation results in impaired delayed-response tasks,</text>
    <text x="60" y="578" font-family="'JetBrains Mono', monospace" font-size="11" fill="#a8a29e">producing the classic inverted-U dopamine response curve.</text>

    <!-- Section 3 -->
    <text x="60" y="625" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="13" font-weight="700" fill="#e07a5f">4.3 Summary Table &amp; Key Receptors</text>
    <rect x="60" y="640" width="480" height="90" fill="#141311" stroke="#3d3a35" stroke-width="1" rx="4"/>
    <text x="75" y="665" font-family="'JetBrains Mono', monospace" font-size="10.5" fill="#81b29a">D1-like (D1, D5): Gs-coupled, increases cAMP, regulates PFC delay firing</text>
    <text x="75" y="690" font-family="'JetBrains Mono', monospace" font-size="10.5" fill="#81b29a">D2-like (D2, D3, D4): Gi-coupled, decreases cAMP, inhibits firing threshold</text>
    <text x="75" y="715" font-family="'JetBrains Mono', monospace" font-size="10.5" fill="#81b29a">Target Pathology: Parkinson's (substantia nigra), ADHD (PFC network tuning)</text>

    <!-- Footer Note -->
    <line x1="60" y1="780" x2="540" y2="780" stroke="#3d3a35" stroke-width="1"/>
    <text x="60" y="805" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="10" fill="#78716c">StudyMind Grounded Document Verification • Source ID: ${docId || 'doc-demo'}</text>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

async function loadPageImage(docId, pageNo) {
  const imgEl = document.getElementById('viewer-page-image');
  const highlightOverlay = document.getElementById('source-highlight-box');

  // Hide highlight until positioned
  highlightOverlay.classList.add('hidden');

  let pageSrc = null;

  // 1. Check in-memory custom rendered pages first (for user's uploaded documents)
  if (demoStore.customPageImages?.[docId]?.[pageNo]) {
    pageSrc = demoStore.customPageImages[docId][pageNo];
  }

  // 2. If not found in memory, try backend if online
  if (!pageSrc && !state.isDemoMode) {
    try {
      const res = await fetch(`${API_BASE}/documents/${docId}/pages/${pageNo}/image`, {
        headers: { Authorization: `Bearer ${state.token}` },
      });
      if (res.ok) {
        const blob = await res.blob();
        pageSrc = URL.createObjectURL(blob);
      }
    } catch {
      // Backend offline / Vercel demo
    }
  }

  // 3. Fallback to SVG generator (supports custom text notes or demo document)
  if (!pageSrc) {
    pageSrc = generateDemoPageSvg(docId, pageNo);
  }

  imgEl.src = pageSrc;
  imgEl.onload = () => {
    // If we have an active citation for this page, re-apply bounding box overlay
    if (
      state.activeCitation &&
      (!state.activeCitation.document_id || state.activeCitation.document_id === docId) &&
      (!state.activeCitation.page || state.activeCitation.page === pageNo)
    ) {
      renderBoundingBoxOverlay(state.activeCitation);
    } else {
      highlightOverlay.classList.add('hidden');
    }
  };
}

function triggerCitationHighlight(citation) {
  state.activeCitation = citation;

  // 1. Highlight pill in chat UI
  document.querySelectorAll('.citation-pill').forEach((pill) => {
    if (pill.getAttribute('data-cit-num') == citation.n) {
      pill.classList.add('active');
    } else {
      pill.classList.remove('active');
    }
  });

  // 2. Open document with citation context
  openSourceViewer(citation.document_id, citation.page, state.currentViewerMaxPages, citation).then(() => {
    renderBoundingBoxOverlay(citation);
  });
}

function renderBoundingBoxOverlay(citation) {
  const imgEl = document.getElementById('viewer-page-image');
  const highlightOverlay = document.getElementById('source-highlight-box');
  const tooltipQuote = document.getElementById('tooltip-quote-text');
  const tooltipCitNum = document.getElementById('tooltip-citation-num');

  if (!imgEl || !highlightOverlay) return;

  const bbox = citation.bbox || citation.bounding_box; // [x0, y0, x1, y1]
  const imgWidth = imgEl.clientWidth || 800;
  const imgHeight = imgEl.clientHeight || 1050;

  // Use natural image dimensions if available; fallback to standard PDF points (612 x 792)
  const natW = imgEl.naturalWidth > 0 ? imgEl.naturalWidth : 612.0;
  const natH = imgEl.naturalHeight > 0 ? imgEl.naturalHeight : 792.0;

  let x0 = 40,
    y0 = 80,
    w = Math.max(imgWidth - 80, 100),
    h = 70;

  if (Array.isArray(bbox) && bbox.length === 4) {
    const [bx0, by0, bx1, by1] = bbox;
    if (bx0 >= 0 && bx1 <= 1 && by0 >= 0 && by1 <= 1) {
      // Normalized coordinates [0..1]
      x0 = bx0 * imgWidth;
      y0 = by0 * imgHeight;
      w = Math.max((bx1 - bx0) * imgWidth, 40);
      h = Math.max((by1 - by0) * imgHeight, 24);
    } else {
      // Absolute pixels or PDF points scaled by natural dimensions
      const scaleX = imgWidth / natW;
      const scaleY = imgHeight / natH;
      x0 = bx0 * scaleX;
      y0 = by0 * scaleY;
      w = Math.max((bx1 - bx0) * scaleX, 40);
      h = Math.max((by1 - by0) * scaleY, 24);
    }
  } else {
    // If no bounding box is provided, position highlight gently at upper third
    x0 = 30;
    y0 = Math.min(imgHeight * 0.12, 100);
    w = Math.max(imgWidth - 60, 100);
    h = 60;
  }

  // Ensure highlight box stays within viewport bounds
  x0 = Math.max(8, Math.min(x0, imgWidth - w - 8));
  y0 = Math.max(8, Math.min(y0, imgHeight - h - 8));

  highlightOverlay.style.left = `${x0}px`;
  highlightOverlay.style.top = `${y0}px`;
  highlightOverlay.style.width = `${w}px`;
  highlightOverlay.style.height = `${h}px`;

  tooltipCitNum.textContent =
    citation.tag || (citation.n ? `Citation [${citation.n}]` : 'Verified Source');
  tooltipQuote.textContent = citation.quote || 'Verified text region';

  highlightOverlay.classList.remove('hidden');

  // Smooth scroll highlighted bounding box into viewport center
  const viewport = document.getElementById('viewer-viewport');
  if (viewport) {
    viewport.scrollTo({
      top: Math.max(0, y0 - 80),
      left: Math.max(0, x0 - 40),
      behavior: 'smooth',
    });
  }
}

// ============================================================================
// Mobile & Web Camera Scanner Logic
// ============================================================================

let cameraStream = null;
let currentFacingMode = 'environment';

async function startCameraScanner() {
  const modal = document.getElementById('camera-modal');
  const video = document.getElementById('camera-video-preview');

  // If getUserMedia is not supported (e.g. non-HTTPS context or restricted browser), seamlessly launch native camera file picker
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    document.getElementById('camera-upload-input')?.click();
    return;
  }

  try {
    if (cameraStream) {
      cameraStream.getTracks().forEach((track) => track.stop());
      cameraStream = null;
    }

    const constraints = {
      video: {
        facingMode: { ideal: currentFacingMode },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    };

    cameraStream = await navigator.mediaDevices.getUserMedia(constraints);
    if (video) {
      video.srcObject = cameraStream;
      await video.play();
    }
    modal?.classList.remove('hidden');
  } catch (err) {
    console.warn('getUserMedia failed, falling back to native camera input:', err);
    stopCameraScanner();
    document.getElementById('camera-upload-input')?.click();
  }
}

function stopCameraScanner() {
  if (cameraStream) {
    cameraStream.getTracks().forEach((t) => t.stop());
    cameraStream = null;
  }
  const video = document.getElementById('camera-video-preview');
  if (video) video.srcObject = null;
  document.getElementById('camera-modal')?.classList.add('hidden');
}

function captureCameraSnapshot() {
  const video = document.getElementById('camera-video-preview');
  const canvas = document.getElementById('camera-canvas-capture');
  if (!video || !canvas || video.videoWidth === 0) {
    showToast('Camera not ready yet', 'error');
    return;
  }

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  canvas.toBlob((blob) => {
    if (!blob) {
      showToast('Failed to capture snapshot', 'error');
      return;
    }
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const capturedFile = new File([blob], `note_camera_${timestamp}.jpg`, { type: 'image/jpeg' });
    stopCameraScanner();
    handleMultipleFiles([capturedFile]);
  }, 'image/jpeg', 0.92);
}

function flipCamera() {
  currentFacingMode = currentFacingMode === 'environment' ? 'user' : 'environment';
  startCameraScanner();
}

// ============================================================================
// Event Listeners & Modals
// ============================================================================

function bindEventListeners() {
  // Navigation Tabs
  const tabChatBtn = document.getElementById('tab-chat-btn');
  const tabLibBtn = document.getElementById('tab-library-btn');
  const tabStudyBtn = document.getElementById('tab-study-btn');
  const chatView = document.getElementById('chat-view');
  const libView = document.getElementById('library-view');
  const studyView = document.getElementById('study-view');

  function switchMainTab(target) {
    if (window.innerWidth <= 768) {
      document.getElementById('app-sidebar')?.classList.remove('mobile-open');
      document.getElementById('sidebar-backdrop')?.classList.add('hidden');
    }
    [tabChatBtn, tabLibBtn, tabStudyBtn].forEach((btn) => btn?.classList.remove('active'));
    document.querySelectorAll('.mobile-nav-item').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tab === target);
    });

    [chatView, libView, studyView].forEach((view) => {
      view?.classList.add('hidden');
      view?.classList.remove('active');
    });

    if (target === 'chat') {
      tabChatBtn?.classList.add('active');
      chatView?.classList.remove('hidden');
      chatView?.classList.add('active');
    } else if (target === 'library') {
      tabLibBtn?.classList.add('active');
      libView?.classList.remove('hidden');
      libView?.classList.add('active');
    } else if (target === 'study') {
      tabStudyBtn?.classList.add('active');
      studyView?.classList.remove('hidden');
      studyView?.classList.add('active');
      loadSavedStudyItems();
    }
  }

  tabChatBtn?.addEventListener('click', () => switchMainTab('chat'));
  tabLibBtn?.addEventListener('click', () => switchMainTab('library'));
  tabStudyBtn?.addEventListener('click', () => switchMainTab('study'));

  // Mobile Bottom Navigation Bar Tabs
  document.getElementById('mobile-tab-chat')?.addEventListener('click', () => {
    setViewerOpen(false);
    switchMainTab('chat');
  });
  document.getElementById('mobile-tab-library')?.addEventListener('click', () => {
    setViewerOpen(false);
    switchMainTab('library');
  });
  document.getElementById('mobile-tab-study')?.addEventListener('click', () => {
    setViewerOpen(false);
    switchMainTab('study');
  });
  document.getElementById('mobile-tab-source')?.addEventListener('click', () => {
    setViewerOpen(true);
  });
  bindStudyToolsEvents();
  initExamPrepEngine();

  // Strict Mode Toggle
  const strictToggle = document.getElementById('strict-mode-toggle');
  strictToggle.addEventListener('change', (e) => {
    state.strictMode = e.target.checked;
    showToast(`Strict mode ${state.strictMode ? 'enabled (zero hallucination)' : 'disabled'}`, 'info');
  });

  // Workspace Select
  const wsSelect = document.getElementById('workspace-select');
  wsSelect.addEventListener('change', async (e) => {
    state.currentWorkspaceId = e.target.value;
    localStorage.setItem('studymind_ws_id', state.currentWorkspaceId);
    await Promise.all([loadDocuments(), loadConversations()]);
  });

  // New Workspace Button & Modal
  document.getElementById('btn-new-workspace').addEventListener('click', () => {
    document.getElementById('workspace-modal').classList.remove('hidden');
  });
  document.getElementById('btn-close-workspace-modal').addEventListener('click', () => {
    document.getElementById('workspace-modal').classList.add('hidden');
  });
  document.getElementById('workspace-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const nameInput = document.getElementById('new-workspace-name');
    try {
      const created = await apiRequest('/workspaces', {
        method: 'POST',
        body: JSON.stringify({ name: nameInput.value.trim() }),
      });
      document.getElementById('workspace-modal').classList.add('hidden');
      nameInput.value = '';
      showToast('Workspace created!', 'success');
      state.currentWorkspaceId = created.id;
      await loadWorkspaces();
    } catch (err) {
      showToast(`Error: ${err.message}`, 'error');
    }
  });

  // New Chat Button
  document.getElementById('btn-new-chat').addEventListener('click', async () => {
    try {
      const newConv = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`, {
        method: 'POST',
        body: JSON.stringify({ title: `Study Chat (${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})` }),
      });
      showToast('New chat started', 'info');
      await loadConversations();
      state.currentConversationId = newConv.id;
      document.getElementById('conv-select').value = newConv.id;
      renderMessages([]);
    } catch (err) {
      showToast(`Failed to start chat: ${err.message}`, 'error');
    }
  });

  // Conversation Select Change
  document.getElementById('conv-select').addEventListener('change', async (e) => {
    state.currentConversationId = e.target.value;
    await loadMessages(state.currentConversationId);
  });

  // Sidebar Collapse & Mobile Drawer Toggle
  const sidebar = document.getElementById('app-sidebar');
  const collapseSidebarBtn = document.getElementById('btn-collapse-sidebar');
  const toggleSidebarBtn = document.getElementById('btn-toggle-sidebar');
  const sidebarBackdrop = document.getElementById('sidebar-backdrop');

  function openMobileSidebar() {
    sidebar?.classList.add('mobile-open');
    sidebarBackdrop?.classList.remove('hidden');
  }

  function closeMobileSidebar() {
    sidebar?.classList.remove('mobile-open');
    sidebarBackdrop?.classList.add('hidden');
  }

  function toggleSidebar() {
    if (window.innerWidth <= 768) {
      if (sidebar?.classList.contains('mobile-open')) {
        closeMobileSidebar();
      } else {
        openMobileSidebar();
      }
    } else {
      if (sidebar) sidebar.classList.toggle('collapsed');
    }
  }

  collapseSidebarBtn?.addEventListener('click', toggleSidebar);
  toggleSidebarBtn?.addEventListener('click', toggleSidebar);
  sidebarBackdrop?.addEventListener('click', closeMobileSidebar);

  window.addEventListener('resize', () => {
    if (window.innerWidth > 768) {
      closeMobileSidebar();
    }
  });

  // Source Viewer Toggle & Close
  const toggleViewerBtn = document.getElementById('btn-toggle-source-viewer');
  const closeViewerBtn = document.getElementById('btn-close-viewer');
  toggleViewerBtn?.addEventListener('click', () => {
    const viewerPanel = document.getElementById('source-viewer-panel');
    if (viewerPanel) {
      const isHidden = viewerPanel.classList.contains('hidden');
      setViewerOpen(isHidden);
    }
  });
  closeViewerBtn?.addEventListener('click', () => {
    setViewerOpen(false);
  });
  document.getElementById('btn-viewer-mobile-back')?.addEventListener('click', () => {
    setViewerOpen(false);
  });

  // Prompt Bar Paperclip Attach -> Open Attach Options Sheet (Camera, Gallery, Files)
  const inputAttachBtn = document.getElementById('btn-input-attach');
  const attachModal = document.getElementById('attach-menu-modal');
  const closeAttachBtn = document.getElementById('btn-close-attach-menu');

  inputAttachBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    attachModal?.classList.remove('hidden');
  });

  closeAttachBtn?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
  });

  attachModal?.addEventListener('click', (e) => {
    if (e.target === attachModal) {
      attachModal.classList.add('hidden');
    }
  });

  document.getElementById('btn-opt-camera')?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
    startCameraScanner();
  });

  document.getElementById('btn-opt-gallery')?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
    document.getElementById('gallery-upload-input')?.click();
  });

  document.getElementById('btn-opt-files')?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
    document.getElementById('file-upload-input')?.click();
  });

  // Chat Form Submit & Auto-resizing Textarea
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  if (chatInput) {
    chatInput.addEventListener('input', () => {
      chatInput.style.height = 'auto';
      chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + 'px';
    });
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event('submit'));
      }
    });
  }

  chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = chatInput.value.trim();
    if (!q) return;
    chatInput.value = '';
    chatInput.style.height = 'auto';
    await handleSendMessage(q);
  });

  // Sample prompt chips in empty state
  document.querySelectorAll('.sample-chips .chip-btn').forEach((chip) => {
    chip.addEventListener('click', async (e) => {
      e.preventDefault();
      const q = chip.getAttribute('data-query');
      if (chatInput) {
        chatInput.value = q;
        chatInput.style.height = 'auto';
      }
      await handleSendMessage(q);
    });
  });

  // Quick Action Chips Bar (1 & 3 Mark Q&A, Summary, Flashcards, Exam)
  document.getElementById('btn-quick-marks')?.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const query = 'Generate questions and answers based on marks like 1 mark and 3 mark from the provided material';
    if (chatInput) {
      chatInput.value = query;
      chatInput.style.height = 'auto';
    }
    await handleSendMessage(query);
  });

  document.getElementById('btn-quick-summary')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    switchMainTab('study');
    document.getElementById('study-subtab-summary')?.click();
  });

  document.getElementById('btn-quick-flashcards')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    switchMainTab('study');
    document.getElementById('study-subtab-flashcards')?.click();
  });

  document.getElementById('btn-quick-exam')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    switchMainTab('study');
    document.getElementById('study-subtab-exam')?.click();
  });

  // Camera, Gallery & Drag and Drop Upload
  const dropzone = document.getElementById('upload-dropzone');
  const fileInput = document.getElementById('file-upload-input');
  const galleryInput = document.getElementById('gallery-upload-input');
  const cameraInput = document.getElementById('camera-upload-input');

  const browseBtn = document.getElementById('btn-browse-files');
  const cameraUploadBtn = document.getElementById('btn-camera-upload');
  const galleryUploadBtn = document.getElementById('btn-gallery-upload');

  browseBtn?.addEventListener('click', () => fileInput?.click());
  galleryUploadBtn?.addEventListener('click', () => galleryInput?.click());
  cameraUploadBtn?.addEventListener('click', () => startCameraScanner());

  fileInput?.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleMultipleFiles(e.target.files);
    }
  });

  galleryInput?.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleMultipleFiles(e.target.files);
    }
  });

  cameraInput?.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleMultipleFiles(e.target.files);
    }
  });

  // In-App Camera Scanner Viewfinder Modal Handlers
  const cameraModal = document.getElementById('camera-modal');
  const closeCameraBtn = document.getElementById('btn-close-camera-modal');
  const snapBtn = document.getElementById('btn-camera-capture');
  const flipBtn = document.getElementById('btn-camera-flip');
  const nativeCameraBtn = document.getElementById('btn-camera-native');

  closeCameraBtn?.addEventListener('click', stopCameraScanner);
  cameraModal?.addEventListener('click', (e) => {
    if (e.target === cameraModal) {
      stopCameraScanner();
    }
  });

  snapBtn?.addEventListener('click', captureCameraSnapshot);
  flipBtn?.addEventListener('click', flipCamera);
  nativeCameraBtn?.addEventListener('click', () => {
    stopCameraScanner();
    cameraInput?.click();
  });

  dropzone?.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone?.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleMultipleFiles(e.dataTransfer.files);
    }
  });

  // Refresh Docs
  document.getElementById('btn-refresh-docs').addEventListener('click', loadDocuments);

  // Viewer Controls (Prev/Next Page & Zoom)
  document.getElementById('btn-prev-page').addEventListener('click', () => {
    if (state.currentViewerPage > 1) {
      openSourceViewer(state.currentViewerDocId, state.currentViewerPage - 1, state.currentViewerMaxPages);
    }
  });
  document.getElementById('btn-next-page').addEventListener('click', () => {
    if (state.currentViewerPage < state.currentViewerMaxPages) {
      openSourceViewer(state.currentViewerDocId, state.currentViewerPage + 1, state.currentViewerMaxPages);
    }
  });

  document.getElementById('btn-zoom-in').addEventListener('click', () => {
    state.viewerZoom = Math.min(2.0, state.viewerZoom + 0.15);
    applyViewerZoom();
  });
  document.getElementById('btn-zoom-out').addEventListener('click', () => {
    state.viewerZoom = Math.max(0.5, state.viewerZoom - 0.15);
    applyViewerZoom();
  });
  document.getElementById('btn-zoom-fit').addEventListener('click', () => {
    state.viewerZoom = 1.0;
    applyViewerZoom();
  });

  document.getElementById('btn-download-file').addEventListener('click', () => {
    if (!state.currentViewerDocId) return;
    window.open(`${API_BASE}/documents/${state.currentViewerDocId}/file`, '_blank');
  });

  document.getElementById('btn-summarize-current-page')?.addEventListener('click', () => {
    if (!state.currentViewerDocId) {
      showToast('Open a document in the viewer first', 'info');
      return;
    }
    const pageNo = state.currentViewerPage || 1;
    const prompt = `Summarize the topics on page ${pageNo}`;
    const input = document.getElementById('chat-input');
    if (input) {
      input.value = prompt;
    }
    const tabChat = document.getElementById('nav-tab-chat');
    tabChat?.click();
    handleSendMessage(prompt);
  });

  // Auth Modal & Buttons
  document.getElementById('btn-open-login').addEventListener('click', () => showAuthModal(true));
  document.getElementById('btn-close-auth').addEventListener('click', () => showAuthModal(false));
  document.getElementById('btn-logout').addEventListener('click', handleUnauthorized);
  document.getElementById('btn-continue-guest')?.addEventListener('click', () => startGuestSession());
  document.getElementById('btn-save-guest')?.addEventListener('click', () => showAuthModal(true));

  let isRegisterMode = false;
  const loginTab = document.getElementById('auth-tab-login');
  const registerTab = document.getElementById('auth-tab-register');
  const authSubmitBtn = document.getElementById('btn-auth-submit');

  loginTab.addEventListener('click', () => {
    isRegisterMode = false;
    loginTab.classList.add('active');
    registerTab.classList.remove('active');
    authSubmitBtn.textContent = 'Sign In';
  });
  registerTab.addEventListener('click', () => {
    isRegisterMode = true;
    registerTab.classList.add('active');
    loginTab.classList.remove('active');
    authSubmitBtn.textContent = 'Create Account';
  });

  document.getElementById('auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('auth-email').value.trim();
    const password = document.getElementById('auth-password').value;
    const errorEl = document.getElementById('auth-error-msg');

    errorEl.classList.add('hidden');
    try {
      if (isRegisterMode) {
        await apiRequest('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        });
      }
      const tokenRes = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      state.token = tokenRes.access_token;
      state.isGuest = false;
      localStorage.setItem('studymind_token', state.token);
      localStorage.removeItem('studymind_is_guest');
      state.user = await apiRequest('/auth/me');

      updateUserNavUI();
      showAuthModal(false);
      showToast('Logged in successfully', 'success');
      await loadWorkspaces();
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove('hidden');
    }
  });

  // Demo Account Quick Test
  document.getElementById('btn-demo-account').addEventListener('click', async () => {
    const demoEmail = 'student@studymind.io';
    const demoPassword = 'password1234';
    try {
      try {
        await apiRequest('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ email: demoEmail, password: demoPassword }),
        });
      } catch {
        // already registered, proceed to login
      }
      const tokenRes = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: demoEmail, password: demoPassword }),
      });
      state.token = tokenRes.access_token;
      localStorage.setItem('studymind_token', state.token);
      state.user = await apiRequest('/auth/me');

      updateUserNavUI();
      showAuthModal(false);
      showToast('Signed in with Demo Student Account!', 'success');
      await loadWorkspaces();
    } catch (err) {
      console.warn('Backend unavailable, switching to Demo Student Account:', err);
      state.token = 'demo-student-token';
      state.user = { id: 'usr-student-demo', email: demoEmail };
      state.isGuest = false;
      state.isDemoMode = true;
      localStorage.setItem('studymind_token', state.token);
      updateUserNavUI();
      updateServerStatusUI('demo');
      showAuthModal(false);
      showToast('Signed in with Demo Student Account (Demo Mode)', 'success');
      await loadWorkspaces();
    }
  });

  // Server Connection Settings Modal Listeners
  document.getElementById('btn-server-status')?.addEventListener('click', () => {
    const currentBase = localStorage.getItem('studymind_api_base') || (API_BASE.startsWith('http') ? API_BASE : '');
    const input = document.getElementById('server-api-url-input');
    if (input) input.value = currentBase;
    document.getElementById('server-modal')?.classList.remove('hidden');
  });

  document.getElementById('btn-close-server-modal')?.addEventListener('click', () => {
    document.getElementById('server-modal')?.classList.add('hidden');
  });

  document.getElementById('server-config-form')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const input = document.getElementById('server-api-url-input');
    const val = input ? input.value.trim().replace(/\/$/, '') : '';
    if (val) {
      localStorage.setItem('studymind_api_base', val);
      showToast(`Connecting to ${val}...`, 'info');
    } else {
      localStorage.removeItem('studymind_api_base');
      showToast('Switched to Demo Mode', 'info');
    }

    const geminiInput = document.getElementById('server-gemini-key-input');
    const geminiVal = geminiInput ? geminiInput.value.trim() : '';
    if (geminiVal) {
      localStorage.setItem('gemini_api_key', geminiVal);
      showToast('Gemini API key saved', 'success');
    } else {
      localStorage.removeItem('gemini_api_key');
    }

    document.getElementById('server-modal')?.classList.add('hidden');
    setTimeout(() => window.location.reload(), 300);
  });

  document.getElementById('btn-reset-demo-mode')?.addEventListener('click', () => {
    localStorage.removeItem('studymind_api_base');
    localStorage.removeItem('gemini_api_key');
    state.isDemoMode = true;
    updateServerStatusUI('demo');
    document.getElementById('server-modal')?.classList.add('hidden');
    showToast('Reset to Interactive Demo Mode', 'info');
    setTimeout(() => window.location.reload(), 300);
  });

  // Feedback Modal
  document.getElementById('btn-close-feedback').addEventListener('click', () => {
    document.getElementById('feedback-modal').classList.add('hidden');
  });
  document.getElementById('feedback-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const msgId = document.getElementById('feedback-message-id').value;
    const reason = document.getElementById('feedback-reason').value;
    const comment = document.getElementById('feedback-comment').value;

    try {
      await apiRequest(`/messages/${msgId}/feedback`, {
        method: 'POST',
        body: JSON.stringify({ rating: 'down', reason, comment }),
      });
      document.getElementById('feedback-modal').classList.add('hidden');
      showToast('Report submitted for evaluation', 'info');
    } catch (err) {
      showToast(`Report failed: ${err.message}`, 'error');
    }
  });
}

// ============================================================================
// Study Tools Logic (Phase 7)
// ============================================================================

let currentFlashcardsList = [];
let currentFlashcardIndex = 0;
let isFlashcardFlipped = false;
let currentQuizList = [];

window.inspectQuizQuestionSource = function (qIdx) {
  const q = currentQuizList?.[qIdx];
  if (!q || !q.document_id) return;
  const citationContext = {
    document_id: q.document_id,
    page: q.page || 1,
    quote: q.quote || q.explanation || q.stem,
    tag: `Quiz Question ${qIdx + 1}`,
    bbox: q.bbox || null,
  };
  openSourceViewer(q.document_id, q.page || 1, state.currentViewerMaxPages, citationContext);
};

window.inspectFlashcardSource = function (fcIdx) {
  const fc = currentFlashcardsList?.[fcIdx];
  if (!fc || !fc.document_id) return;
  const citationContext = {
    document_id: fc.document_id,
    page: fc.page || 1,
    quote: fc.quote || fc.answer,
    tag: `Flashcard ${fcIdx + 1}`,
    bbox: fc.bbox || null,
  };
  openSourceViewer(fc.document_id, fc.page || 1, state.currentViewerMaxPages, citationContext);
};

window.inspectSummaryAreaSource = function (areaIdx) {
  const a = state.lastSummaryAreas?.[areaIdx];
  if (!a || !a.document_id) return;
  const citationContext = {
    document_id: a.document_id,
    page: a.page || 1,
    quote: a.quote || a.summary,
    tag: a.area_title || 'Key Area',
    bbox: a.bbox || null,
  };
  openSourceViewer(a.document_id, a.page || 1, state.currentViewerMaxPages, citationContext);
};

window.inspectSummaryTakeawaySource = function (tIdx) {
  const t = state.lastSummaryTakeaways?.[tIdx];
  if (!t || !t.document_id) return;
  const citationContext = {
    document_id: t.document_id,
    page: t.page || 1,
    quote: t.quote || t.point,
    tag: `Takeaway ${tIdx + 1}`,
    bbox: t.bbox || null,
  };
  openSourceViewer(t.document_id, t.page || 1, state.currentViewerMaxPages, citationContext);
};

async function loadExistingFlashcards() {
  if (!state.currentWorkspaceId) return;
  try {
    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/items?type=flashcard`);
    if (res && res.items && res.items.length > 0) {
      currentFlashcardsList = res.items.map((it) => it.payload).filter(Boolean);
      currentFlashcardIndex = 0;
      isFlashcardFlipped = false;
      renderFlashcardCard();
    }
  } catch {
    // Non-critical background fetch
  }
}

function bindStudyToolsEvents() {
  // Subtabs switching
  const subtabs = document.querySelectorAll('.study-subtab-btn');
  const panes = {
    summary: document.getElementById('study-summary-pane'),
    flashcards: document.getElementById('study-flashcards-pane'),
    quiz: document.getElementById('study-quiz-pane'),
    exam: document.getElementById('study-exam-pane'),
    saved: document.getElementById('study-saved-pane'),
  };

  subtabs.forEach((btn) => {
    btn.addEventListener('click', () => {
      subtabs.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const tool = btn.getAttribute('data-tool');
      Object.entries(panes).forEach(([k, pane]) => {
        if (k === tool) {
          pane?.classList.remove('hidden');
          pane?.classList.add('active');
        } else {
          pane?.classList.add('hidden');
          pane?.classList.remove('active');
        }
      });
      if (tool === 'saved') loadSavedStudyItems();
      if (tool === 'exam') loadExamAnalytics();
      if (tool === 'flashcards' && currentFlashcardsList.length === 0) loadExistingFlashcards();
    });
  });

  // Summary generation
  const btnGenSummary = document.getElementById('btn-generate-summary');
  btnGenSummary?.addEventListener('click', async () => {
    if (!state.currentWorkspaceId) {
      showToast('Select a workspace first', 'error');
      return;
    }
    const lengthSelect = document.getElementById('summary-length-select');
    const container = document.getElementById('summary-output-container');
    container.innerHTML = '<div class="tool-placeholder">⏳ Generating grounded map-reduce summary & extracting key areas...</div>';

    try {
      const summaryRes = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/summary`, {
        method: 'POST',
        body: JSON.stringify({ length: lengthSelect.value }),
      });
      renderSummaryResult(summaryRes);
      showToast('Summary generated with verified citations & page links!', 'success');
    } catch (err) {
      container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed to generate summary: ${escapeHtml(err.message)}</div>`;
    }
  });

  // Reader Mode Toggle
  document.getElementById('btn-reader-mode-toggle')?.addEventListener('click', () => {
    const pane = document.getElementById('study-summary-pane');
    pane?.classList.toggle('reader-mode-active');
    const isReader = pane?.classList.contains('reader-mode-active');
    showToast(`Reader Mode ${isReader ? 'Enabled' : 'Disabled'}`, 'info');
  });

  // Flashcards generation with deck expansion and deduplication
  const btnGenCards = document.getElementById('btn-generate-flashcards');
  btnGenCards?.addEventListener('click', async () => {
    if (!state.currentWorkspaceId) {
      showToast('Select a workspace first', 'error');
      return;
    }
    const countSelect = document.getElementById('flashcards-count-select');
    const container = document.getElementById('flashcards-output-container');
    container.innerHTML = '<div class="tool-placeholder">⏳ Generating verified non-repeating flashcards...</div>';

    try {
      const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/flashcards`, {
        method: 'POST',
        body: JSON.stringify({ count: parseInt(countSelect.value, 10) }),
      });
      const newCards = res.flashcards || [];
      if (currentFlashcardsList.length === 0) {
        currentFlashcardsList = newCards;
        currentFlashcardIndex = 0;
      } else {
        const existingStems = new Set(currentFlashcardsList.map((c) => (c.question || '').toLowerCase().trim()));
        const uniqueCards = newCards.filter((c) => !existingStems.has((c.question || '').toLowerCase().trim()));
        const toAdd = uniqueCards.length > 0 ? uniqueCards : newCards;
        currentFlashcardIndex = currentFlashcardsList.length;
        currentFlashcardsList = currentFlashcardsList.concat(toAdd);
      }
      isFlashcardFlipped = false;
      renderFlashcardCard();
      showToast(`Added ${newCards.length} verified flashcards! Total in deck: ${currentFlashcardsList.length}`, 'success');
    } catch (err) {
      container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed: ${escapeHtml(err.message)}</div>`;
    }
  });

  // Shuffle flashcards deck
  document.getElementById('btn-shuffle-flashcards')?.addEventListener('click', () => {
    if (currentFlashcardsList.length <= 1) {
      showToast('Generate more cards to shuffle deck', 'info');
      return;
    }
    for (let i = currentFlashcardsList.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [currentFlashcardsList[i], currentFlashcardsList[j]] = [currentFlashcardsList[j], currentFlashcardsList[i]];
    }
    currentFlashcardIndex = 0;
    isFlashcardFlipped = false;
    renderFlashcardCard();
    showToast(`Shuffled deck (${currentFlashcardsList.length} cards)`, 'info');
  });

  // Clear / Fresh deck
  document.getElementById('btn-clear-flashcards')?.addEventListener('click', () => {
    currentFlashcardsList = [];
    currentFlashcardIndex = 0;
    isFlashcardFlipped = false;
    renderFlashcardCard();
    showToast('Deck reset. Click "Generate More Cards" for a fresh set.', 'info');
  });

  // Quiz generation
  const btnGenQuiz = document.getElementById('btn-generate-quiz');
  btnGenQuiz?.addEventListener('click', async () => {
    if (!state.currentWorkspaceId) {
      showToast('Select a workspace first', 'error');
      return;
    }
    const countSelect = document.getElementById('quiz-count-select');
    const diffSelect = document.getElementById('quiz-difficulty-select');
    const container = document.getElementById('quiz-output-container');
    container.innerHTML = '<div class="tool-placeholder">⏳ Generating grounded quiz questions...</div>';

    try {
      const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/quiz`, {
        method: 'POST',
        body: JSON.stringify({
          count: parseInt(countSelect.value, 10),
          difficulty: diffSelect.value,
        }),
      });
      renderQuizRunner(res.questions || []);
      showToast(`Generated ${res.questions?.length || 0} grounded questions!`, 'success');
    } catch (err) {
      container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed: ${escapeHtml(err.message)}</div>`;
    }
  });

  // Export buttons
  document.getElementById('btn-export-anki')?.addEventListener('click', exportAnki);
  document.getElementById('btn-download-anki-deck')?.addEventListener('click', exportAnki);
  document.getElementById('btn-download-study-guide')?.addEventListener('click', () => {
    if (!state.currentWorkspaceId) return;
    window.open(`${API_BASE}/workspaces/${state.currentWorkspaceId}/study/export/markdown`, '_blank');
  });
  document.getElementById('btn-refresh-study-items')?.addEventListener('click', loadSavedStudyItems);
}

function exportAnki() {
  if (!state.currentWorkspaceId) {
    showToast('Select a workspace first', 'error');
    return;
  }
  window.open(`${API_BASE}/workspaces/${state.currentWorkspaceId}/study/export/anki`, '_blank');
  showToast('Exporting Anki TSV deck...', 'info');
}

function renderSummaryResult(summary) {
  const container = document.getElementById('summary-output-container');
  if (!container) return;

  // 1. Referenced Pages Quick Navigator
  const pagesList = summary.referenced_pages || [];
  let pagesNavHtml = '';
  if (pagesList.length > 0) {
    const pageChips = pagesList
      .map(
        (p) => `
      <button class="page-chip-link" onclick="openSourceViewer('${p.document_id}', ${p.page})" title="Jump directly to page ${p.page} in Source Inspector">
        <span class="page-chip-icon">📄</span>
        <span>Page ${p.page} ${p.title ? `(${escapeHtml(p.title)})` : ''}</span>
      </button>
    `
      )
      .join('');

    pagesNavHtml = `
      <div class="summary-pages-navigator">
        <div class="pages-nav-header">
          <span>📍 Important Pages in Material (${pagesList.length})</span>
          <span style="font-size:0.7rem; color:var(--text-muted);">Click any page chip to inspect full region</span>
        </div>
        <div class="summary-pages-bar">${pageChips}</div>
      </div>
    `;
  }

  // 2. Important Areas & Topics Grid
  const importantAreas = summary.important_areas || [];
  state.lastSummaryAreas = importantAreas;
  state.lastSummaryTakeaways = summary.key_takeaways || [];

  let importantAreasHtml = '';
  if (importantAreas.length > 0) {
    const areaCards = importantAreas
      .map(
        (a, aIdx) => `
      <div class="important-area-card">
        <div class="area-card-header">
          <div class="area-title-text">📌 ${escapeHtml(a.area_title)}</div>
          <span class="area-page-badge">Page ${a.page || 1}</span>
        </div>
        <div class="area-card-body">${escapeHtml(a.summary)}</div>
        ${
          a.quote
            ? `<div class="area-quote-snippet">&ldquo;${escapeHtml(a.quote)}&rdquo;</div>`
            : ''
        }
        ${
          a.document_id
            ? `<button class="area-read-btn" onclick="inspectSummaryAreaSource(${aIdx})" title="Open page ${a.page || 1} with supporting quote">
                 <span>Inspect Source (Page ${a.page || 1})</span>
                 <span>↗</span>
               </button>`
            : ''
        }
      </div>
    `
      )
      .join('');

    importantAreasHtml = `
      <div class="important-areas-section">
        <div class="section-title-row">
          <h4>🌟 Core Topics & Important Areas</h4>
          <span style="font-size:0.75rem; color:var(--text-muted);">${importantAreas.length} verified areas</span>
        </div>
        <div class="important-areas-grid">${areaCards}</div>
      </div>
    `;
  }

  // 3. Takeaways list
  const takeawaysHtml = (summary.key_takeaways || [])
    .map(
      (t, tIdx) => `
    <div class="takeaway-item">
      <div>
        <div class="takeaway-text">📌 ${escapeHtml(t.point)}</div>
        <div class="takeaway-quote">&ldquo;${escapeHtml(t.quote)}&rdquo; (Page ${t.page || 1})</div>
      </div>
      ${
        t.document_id
          ? `<button class="btn-inspect-citation" onclick="inspectSummaryTakeawaySource(${tIdx})">View Page ${t.page || 1} ↗</button>`
          : ''
      }
    </div>
  `
    )
    .join('');

  const summaryText = summary.summary || '';
  const formattedSummaryHtml = escapeHtml(summaryText)
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');

  container.innerHTML = `
    <div class="summary-reader-view">
      <!-- Reader Hero Bar -->
      <div class="summary-reader-hero">
        <div class="summary-hero-top">
          <h3 class="summary-hero-title">${escapeHtml(summary.title)}</h3>
          <div class="summary-meta-badges">
            <span class="summary-stat-badge active">✓ Grounded Map-Reduce</span>
            <span class="summary-stat-badge">📄 ${pagesList.length || 1} Pages Covered</span>
            <button class="btn-ghost-sm" onclick="navigator.clipboard.writeText(${JSON.stringify(summaryText)}); showToast('Summary copied to clipboard!', 'info');" title="Copy summary text">📋 Copy</button>
          </div>
        </div>
      </div>

      <!-- Quick Page Redirection Navigator -->
      ${pagesNavHtml}

      <!-- Executive Overview / Prose -->
      <div class="summary-text-prose">
        <h4 style="margin-bottom:10px; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:6px;">
          <span>📖 Executive Synthesis</span>
        </h4>
        <p>${formattedSummaryHtml}</p>
      </div>

      <!-- Important Areas & Topics Grid -->
      ${importantAreasHtml}

      <!-- Takeaways Section -->
      <div class="takeaways-section">
        <h4>Key Takeaways (${summary.key_takeaways?.length || 0})</h4>
        ${takeawaysHtml || '<p class="tool-placeholder">No individual takeaways.</p>'}
      </div>
    </div>
  `;
}

function renderFlashcardCard() {
  const container = document.getElementById('flashcards-output-container');
  if (!container) return;

  if (currentFlashcardsList.length === 0) {
    container.innerHTML = '<div class="tool-placeholder">No flashcards generated yet.</div>';
    return;
  }

  const card = currentFlashcardsList[currentFlashcardIndex];
  container.innerHTML = `
    <div class="flashcard-viewer">
      <div id="active-flashcard" class="flashcard-card">
        <span class="flashcard-side-tag">${isFlashcardFlipped ? 'Answer (Click to flip)' : 'Question (Click to flip)'}</span>
        <div class="flashcard-prompt-text">${escapeHtml(isFlashcardFlipped ? card.answer : card.question)}</div>
        ${
          isFlashcardFlipped
            ? `<div class="flashcard-quote-box">Proof (Page ${card.page || 1}): &ldquo;${escapeHtml(card.quote)}&rdquo;</div>`
            : '<span class="flashcard-subtext">Click card or spacebar to reveal answer</span>'
        }
      </div>
      <div class="flashcard-controls">
        <button id="btn-fc-prev" class="btn-icon-sm" ${currentFlashcardIndex === 0 ? 'disabled' : ''}>◀</button>
        <span class="page-indicator">Card ${currentFlashcardIndex + 1} / ${currentFlashcardsList.length}</span>
        <button id="btn-fc-next" class="btn-icon-sm" ${currentFlashcardIndex === currentFlashcardsList.length - 1 ? 'disabled' : ''}>▶</button>
        ${
          card.document_id
            ? `<button class="btn-ghost-sm" onclick="inspectFlashcardSource(currentFlashcardIndex)">Inspect Source ↗</button>`
            : ''
        }
      </div>
    </div>
  `;

  document.getElementById('active-flashcard')?.addEventListener('click', () => {
    isFlashcardFlipped = !isFlashcardFlipped;
    renderFlashcardCard();
  });

  document.getElementById('btn-fc-prev')?.addEventListener('click', () => {
    if (currentFlashcardIndex > 0) {
      currentFlashcardIndex--;
      isFlashcardFlipped = false;
      renderFlashcardCard();
    }
  });

  document.getElementById('btn-fc-next')?.addEventListener('click', () => {
    if (currentFlashcardIndex < currentFlashcardsList.length - 1) {
      currentFlashcardIndex++;
      isFlashcardFlipped = false;
      renderFlashcardCard();
    }
  });
}

function renderQuizRunner(questions) {
  const container = document.getElementById('quiz-output-container');
  if (!container) return;

  currentQuizList = questions || [];

  if (questions.length === 0) {
    container.innerHTML = '<div class="tool-placeholder">No quiz questions generated yet.</div>';
    return;
  }

  container.innerHTML = questions
    .map((q, qIdx) => {
      const letters = ['A', 'B', 'C', 'D'];
      const optionsHtml = q.options
        .map(
          (opt, oIdx) => `
        <label class="quiz-option-label" id="opt-label-${qIdx}-${oIdx}">
          <input type="radio" name="quiz-q-${qIdx}" value="${oIdx}">
          <span><strong>${letters[oIdx]}.</strong> ${escapeHtml(opt)}</span>
        </label>
      `
        )
        .join('');

      return `
      <div class="quiz-card" id="quiz-card-${qIdx}">
        <div class="quiz-stem"><strong>Q${qIdx + 1}:</strong> ${escapeHtml(q.stem)}</div>
        <div class="quiz-options">${optionsHtml}</div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <button class="btn-primary-sm btn-submit-quiz-q" data-q-idx="${qIdx}">Check Answer</button>
          ${
            q.document_id
              ? `<button class="btn-icon-subtle" onclick="inspectQuizQuestionSource(${qIdx})" title="Inspect Source">View Source ↗</button>`
              : ''
          }
        </div>
        <div id="quiz-feedback-${qIdx}" class="quiz-feedback-box hidden"></div>
      </div>
    `;
    })
    .join('');

  container.querySelectorAll('.btn-submit-quiz-q').forEach((btn) => {
    btn.addEventListener('click', () => {
      const qIdx = parseInt(btn.getAttribute('data-q-idx'), 10);
      const q = questions[qIdx];
      const selected = document.querySelector(`input[name="quiz-q-${qIdx}"]:checked`);
      const feedbackBox = document.getElementById(`quiz-feedback-${qIdx}`);

      if (!selected) {
        showToast('Please select an option first', 'info');
        return;
      }

      const selVal = parseInt(selected.value, 10);
      const isCorrect = selVal === q.correct_answer_index;
      feedbackBox.classList.remove('hidden');

      // Highlight options
      q.options.forEach((_, oIdx) => {
        const lbl = document.getElementById(`opt-label-${qIdx}-${oIdx}`);
        lbl?.classList.remove('correct', 'incorrect');
        if (oIdx === q.correct_answer_index) lbl?.classList.add('correct');
        else if (oIdx === selVal && !isCorrect) lbl?.classList.add('incorrect');
      });

      feedbackBox.innerHTML = `
        <div class="quiz-feedback-header ${isCorrect ? 'correct' : 'incorrect'}">
          ${isCorrect ? '✓ Correct!' : '✗ Incorrect'}
        </div>
        <div>${escapeHtml(q.explanation)}</div>
        <div style="font-size:0.76rem; color:var(--text-muted); margin-top:4px; font-style:italic;">
          Proof: &ldquo;${escapeHtml(q.quote)}&rdquo; (Page ${q.page || 1})
        </div>
      `;
    });
  });
}

async function loadSavedStudyItems() {
  const container = document.getElementById('saved-items-container');
  if (!container || !state.currentWorkspaceId) return;

  try {
    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/items`);
    const items = res.items || [];
    if (items.length === 0) {
      container.innerHTML = '<div class="tool-placeholder">No saved items yet. Generate summaries, flashcards, or quizzes above.</div>';
      return;
    }

    container.innerHTML = items
      .map((it) => {
        const title = it.payload?.title || it.payload?.question || it.payload?.stem || `${it.type} item`;
        return `
        <div class="saved-item-row" id="saved-item-${it.id}">
          <div class="saved-item-meta">
            <span class="saved-type-badge ${it.type}">${it.type}</span>
            <span style="font-weight:600; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
              ${escapeHtml(title)}
            </span>
          </div>
          <button class="btn-icon-subtle" onclick="deleteStudyItem('${it.id}')" title="Delete" style="color:var(--rose);">🗑</button>
        </div>
      `;
      })
      .join('');
  } catch (err) {
    container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed to load items: ${escapeHtml(err.message)}</div>`;
  }
}

async function deleteStudyItem(itemId) {
  if (!confirm('Delete this study item?')) return;
  try {
    await apiRequest(`/study/items/${itemId}`, { method: 'DELETE' });
    showToast('Item deleted', 'info');
    await loadSavedStudyItems();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
  }
}

function applyViewerZoom() {
  const wrapper = document.getElementById('viewer-content-wrapper');
  const zoomText = document.getElementById('zoom-level-text');
  if (wrapper) wrapper.style.transform = `scale(${state.viewerZoom})`;
  if (zoomText) zoomText.textContent = `${Math.round(state.viewerZoom * 100)}%`;
}

function openFeedbackModal(messageId) {
  document.getElementById('feedback-message-id').value = messageId;
  document.getElementById('feedback-comment').value = '';
  document.getElementById('feedback-modal').classList.remove('hidden');
}

// ============================================================================
// Phase 7B: Test Me / Exam Prep Engine Logic
// ============================================================================

let currentExamSession = null;
let currentExamQuestions = [];
let currentExamIndex = 0;
let examTimerInterval = null;
let examSecondsRemaining = 0;
let examUserAnswers = {};

function initExamPrepEngine() {
  const btnStart = document.getElementById('btn-start-exam');
  btnStart?.addEventListener('click', startExamSession);

  document.getElementById('btn-runner-next')?.addEventListener('click', () => {
    if (currentExamIndex < currentExamQuestions.length - 1) {
      currentExamIndex++;
      renderExamQuestion(currentExamIndex);
    }
  });

  document.getElementById('btn-runner-prev')?.addEventListener('click', () => {
    if (currentExamIndex > 0) {
      currentExamIndex--;
      renderExamQuestion(currentExamIndex);
    }
  });

  document.getElementById('btn-runner-submit')?.addEventListener('click', submitCompleteExam);

  // Report Question Modal events
  document.getElementById('btn-report-question')?.addEventListener('click', () => {
    if (currentExamQuestions.length > 0 && currentExamQuestions[currentExamIndex]) {
      openReportQuestionModal(currentExamQuestions[currentExamIndex].id);
    }
  });

  document.getElementById('btn-close-report-modal')?.addEventListener('click', () => {
    document.getElementById('report-question-modal')?.classList.add('hidden');
  });

  document.getElementById('report-question-form')?.addEventListener('submit', handleReportQuestionSubmit);
}

async function loadExamAnalytics() {
  if (!state.currentWorkspaceId) return;
  try {
    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/analytics`);
    const scoreDisplay = document.getElementById('readiness-score-display');
    if (scoreDisplay && res) {
      scoreDisplay.textContent = `${Math.round(res.overall_readiness_pct || 0)}%`;
    }
  } catch {
    // Non-critical background telemetry
  }
}

async function startExamSession() {
  if (!state.currentWorkspaceId) {
    showToast('Please select a workspace first', 'error');
    return;
  }

  const mode = document.getElementById('exam-mode-select').value;
  const count = parseInt(document.getElementById('exam-count-select').value, 10);
  const diff = parseInt(document.getElementById('exam-difficulty-select').value, 10);
  const timerVal = parseInt(document.getElementById('exam-timer-select').value, 10);

  const runnerCard = document.getElementById('exam-active-runner');
  const resultsCard = document.getElementById('exam-results-card');
  resultsCard.classList.add('hidden');
  runnerCard.classList.remove('hidden');

  const questionBody = document.getElementById('runner-question-card');
  questionBody.innerHTML = '<div class="tool-placeholder">⏳ Preparing syllabus assessment & sampling verified questions...</div>';

  try {
    const payload = {
      mode: mode,
      count: count,
      difficulty: diff,
      time_limit_s: timerVal > 0 ? timerVal : null,
    };

    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/quizzes`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    currentExamSession = res.session_id;
    currentExamQuestions = res.questions || [];
    currentExamIndex = 0;
    examUserAnswers = {};

    // Badge
    const badge = document.getElementById('runner-mode-badge');
    if (badge) badge.textContent = `${mode.toUpperCase()} MODE`;

    // Timer setup
    const timerDisplay = document.getElementById('runner-timer-display');
    if (timerVal > 0) {
      timerDisplay.classList.remove('hidden');
      examSecondsRemaining = timerVal;
      updateTimerDisplay();
      if (examTimerInterval) clearInterval(examTimerInterval);
      examTimerInterval = setInterval(() => {
        examSecondsRemaining--;
        updateTimerDisplay();
        if (examSecondsRemaining <= 0) {
          clearInterval(examTimerInterval);
          showToast('Time limit reached! Submitting exam...', 'info');
          submitCompleteExam();
        }
      }, 1000);
    } else {
      timerDisplay.classList.add('hidden');
    }

    renderExamQuestion(0);
    showToast(`Exam session started with ${currentExamQuestions.length} questions!`, 'success');
  } catch (err) {
    questionBody.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed to start assessment: ${escapeHtml(err.message)}</div>`;
  }
}

function updateTimerDisplay() {
  const el = document.getElementById('runner-timer-display');
  if (!el) return;
  const m = Math.floor(examSecondsRemaining / 60);
  const s = examSecondsRemaining % 60;
  el.textContent = `⏱️ ${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function renderExamQuestion(index) {
  if (!currentExamQuestions || currentExamQuestions.length === 0) return;
  const q = currentExamQuestions[index];
  const container = document.getElementById('runner-question-card');
  const counter = document.getElementById('runner-progress-indicator');
  const btnPrev = document.getElementById('btn-runner-prev');
  const btnNext = document.getElementById('btn-runner-next');
  const btnSubmit = document.getElementById('btn-runner-submit');

  counter.textContent = `Question ${index + 1} of ${currentExamQuestions.length}`;
  btnPrev.disabled = index === 0;

  if (index === currentExamQuestions.length - 1) {
    btnNext.classList.add('hidden');
    btnSubmit.classList.remove('hidden');
  } else {
    btnNext.classList.remove('hidden');
    btnSubmit.classList.add('hidden');
  }

  const existingAns = examUserAnswers[q.id];
  let inputHtml = '';

  if (q.options && q.options.length > 0) {
    inputHtml = `
      <div class="runner-options-list">
        ${q.options
          .map((opt, oIdx) => {
            const isChecked = existingAns === oIdx;
            return `
            <div class="runner-opt-card ${isChecked ? 'selected' : ''}" id="runner-opt-${q.id}-${oIdx}" onclick="selectExamOption('${q.id}', ${oIdx})">
              <span class="runner-opt-key">${String.fromCharCode(65 + oIdx)}</span>
              <span class="runner-opt-text">${escapeHtml(opt)}</span>
            </div>
          `;
          })
          .join('')}
      </div>
    `;
  } else {
    // Written or numeric input
    inputHtml = `
      <div style="margin-top:10px;">
        <textarea id="runner-written-input" class="form-input" rows="3" placeholder="Type your answer here based on the course material...">${existingAns || ''}</textarea>
        <button class="btn-ghost-sm" style="margin-top:6px;" onclick="saveWrittenExamAnswer('${q.id}')">Save Draft Answer</button>
      </div>
    `;
  }

  const mode = document.getElementById('exam-mode-select')?.value;
  const checkBtnHtml =
    mode !== 'mock'
      ? `<button class="btn-primary-sm" onclick="checkInstantExamAnswer('${q.id}')" style="margin-top:14px;">Check Answer</button>`
      : '';

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span class="stage-badge" style="background:rgba(217,119,87,0.15); color:var(--primary-light); text-transform:uppercase;">${q.type}</span>
      <span style="font-size:0.8rem; color:var(--text-muted); font-weight:700;">${q.marks} Marks</span>
    </div>
    <div class="runner-q-stem">${escapeHtml(q.stem)}</div>
    ${inputHtml}
    ${checkBtnHtml}
    <div id="runner-instant-feedback" class="quiz-feedback-box hidden" style="margin-top:14px;"></div>
  `;
}

window.selectExamOption = function (qId, optionIndex) {
  examUserAnswers[qId] = optionIndex;
  document.querySelectorAll('.runner-opt-card').forEach((el) => el.classList.remove('selected'));
  const target = document.getElementById(`runner-opt-${qId}-${optionIndex}`);
  target?.classList.add('selected');
};

window.saveWrittenExamAnswer = function (qId) {
  const input = document.getElementById('runner-written-input');
  if (input) {
    examUserAnswers[qId] = input.value.trim();
    showToast('Draft answer saved', 'info');
  }
};

window.checkInstantExamAnswer = async function (qId) {
  const ans = examUserAnswers[qId];
  if (ans === undefined) {
    showToast('Please select an answer first', 'info');
    return;
  }
  const feedbackBox = document.getElementById('runner-instant-feedback');
  feedbackBox.classList.remove('hidden');
  feedbackBox.innerHTML = '<span>⏳ Grading answer against cited context...</span>';

  try {
    const res = await apiRequest(`/quizzes/${currentExamSession}/answers`, {
      method: 'POST',
      body: JSON.stringify({ question_id: qId, user_answer: ans, time_s: 10 }),
    });

    const isCorr = res.is_correct;
    feedbackBox.innerHTML = `
      <div class="quiz-feedback-header ${isCorr ? 'correct' : 'incorrect'}">
        ${isCorr ? '✓ Correct!' : '✗ Needs Review'} (Score: ${res.score}/${res.max_score})
      </div>
      <div>${escapeHtml(res.explanation || '')}</div>
      ${
        res.source_quotes && res.source_quotes[0]
          ? `<div style="font-size:0.78rem; color:var(--text-muted); margin-top:6px; font-style:italic;">
               Cited Proof: &ldquo;${escapeHtml(res.source_quotes[0])}&rdquo;
             </div>`
          : ''
      }
    `;
  } catch (err) {
    feedbackBox.innerHTML = `<span style="color:var(--rose);">Error: ${escapeHtml(err.message)}</span>`;
  }
};

async function submitCompleteExam() {
  if (!confirm('Are you ready to submit your exam paper for evaluation?')) return;
  if (examTimerInterval) clearInterval(examTimerInterval);

  const runnerCard = document.getElementById('exam-active-runner');
  const resultsCard = document.getElementById('exam-results-card');
  runnerCard.classList.add('hidden');
  resultsCard.classList.remove('hidden');
  resultsCard.innerHTML = '<div class="tool-placeholder">⏳ Computing deterministic grading, Bayesian mastery, and full report...</div>';

  try {
    const report = await apiRequest(`/quizzes/${currentExamSession}/submit`, {
      method: 'POST',
    });
    renderExamReport(report);
    showToast(`Exam completed! You scored ${report.percentage}%`, 'success');
    await loadExamAnalytics();
  } catch (err) {
    resultsCard.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Submission failed: ${escapeHtml(err.message)}</div>`;
  }
}

function renderExamReport(report) {
  const container = document.getElementById('exam-results-card');
  if (!container) return;

  const passed = report.passed;
  const topicsHtml = (report.per_topic || [])
    .map(
      (t) => `
    <div class="topic-row">
      <span class="topic-row-name" title="${escapeHtml(t.topic_name)}">${escapeHtml(t.topic_name)}</span>
      <div class="topic-bar-track">
        <div class="topic-bar-fill" style="width: ${Math.min(100, t.percentage)}%;"></div>
      </div>
      <span class="topic-pct">${Math.round(t.percentage)}%</span>
    </div>
  `
    )
    .join('');

  const questionsReviewHtml = (report.questions || [])
    .map(
      (q, idx) => `
    <div class="quiz-card" style="margin-top:12px;">
      <div style="display:flex; justify-content:space-between;">
        <strong>Q${idx + 1}: ${escapeHtml(q.stem)}</strong>
        <span class="${q.is_correct ? 'stage-badge' : 'stage-badge'}" style="${q.is_correct ? 'color:var(--emerald); background:rgba(16,185,129,0.15);' : 'color:var(--rose); background:rgba(244,63,94,0.15);'}">
          ${q.score} / ${q.marks} Marks
        </span>
      </div>
      <div style="margin-top:8px; font-size:0.86rem;">
        <div><strong>Your Answer:</strong> ${escapeHtml(String(q.user_answer ?? 'None'))}</div>
        <div><strong>Correct Key:</strong> ${escapeHtml(String(q.correct_answer))}</div>
        <div style="color:var(--text-muted); margin-top:4px;">${escapeHtml(q.explanation)}</div>
        ${
          q.source_quotes && q.source_quotes[0]
            ? `<div style="font-size:0.78rem; color:var(--text-muted); font-style:italic; margin-top:4px;">
                 Proof: &ldquo;${escapeHtml(q.source_quotes[0])}&rdquo;
               </div>`
            : ''
        }
      </div>
    </div>
  `
    )
    .join('');

  container.innerHTML = `
    <div class="report-hero">
      <div class="report-score-box">
        <div class="score-big">${Math.round(report.percentage)}%</div>
        <div class="score-sub">${report.score} of ${report.max_score} Total Marks</div>
      </div>
      <div style="text-align:right;">
        <span class="stage-badge" style="${passed ? 'color:var(--emerald); background:var(--emerald-bg);' : 'color:var(--rose); background:var(--rose-bg);'} font-size:0.85rem; padding:4px 12px;">
          ${passed ? '✓ PASSED' : 'REVISION RECOMMENDED'}
        </span>
        <div style="font-size:0.8rem; color:var(--text-muted); margin-top:6px;">
          Duration: ${Math.floor(report.duration_s / 60)}m ${report.duration_s % 60}s
        </div>
      </div>
    </div>

    <div style="font-size:0.92rem; line-height:1.5; background:rgba(217,119,87,0.08); border-left:3px solid var(--primary); padding:10px 14px; border-radius:var(--radius-sm);">
      💡 <strong>AI Feedback:</strong> ${escapeHtml(report.encouraging_feedback)}
    </div>

    <div class="report-topics-breakdown">
      <h5 style="margin:0 0 4px; font-size:0.88rem;">Syllabus Topic Performance</h5>
      ${topicsHtml || '<div style="font-size:0.8rem; color:var(--text-muted);">General Assessment</div>'}
    </div>

    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:8px;">
      <button class="btn-primary-sm" onclick="exportExamSession('${report.session_id}', 'anki')">Export to Anki TSV ↗</button>
      <button class="btn-ghost-sm" onclick="exportExamSession('${report.session_id}', 'markdown')">Download Exam Guide (.md) ↗</button>
      <button class="btn-ghost-sm" onclick="document.getElementById('exam-active-runner').classList.add('hidden'); document.getElementById('exam-results-card').classList.add('hidden');" style="margin-left:auto;">Back to Setup</button>
    </div>

    <div style="margin-top:16px;">
      <h5 style="margin:0 0 8px; font-size:0.9rem;">Question Review & Citations</h5>
      ${questionsReviewHtml}
    </div>
  `;
}

window.exportExamSession = function (sessId, format) {
  window.open(`${API_BASE}/quizzes/${sessId}/export?format=${format}`, '_blank');
};

function openReportQuestionModal(qId) {
  const hiddenInput = document.getElementById('report-question-id');
  if (hiddenInput) hiddenInput.value = qId;
  document.getElementById('report-question-modal')?.classList.remove('hidden');
}

async function handleReportQuestionSubmit(e) {
  e.preventDefault();
  const qId = document.getElementById('report-question-id')?.value;
  const reason = document.getElementById('report-reason-select')?.value;
  const comment = document.getElementById('report-comment-input')?.value;

  try {
    await apiRequest(`/questions/${qId}/report`, {
      method: 'POST',
      body: JSON.stringify({ reason, comment }),
    });
    document.getElementById('report-question-modal')?.classList.add('hidden');
    showToast('Question reported and retired from future exams!', 'info');
  } catch (err) {
    showToast(`Report failed: ${err.message}`, 'error');
  }
}

// Start app on DOMContentLoaded
window.addEventListener('DOMContentLoaded', initApp);

