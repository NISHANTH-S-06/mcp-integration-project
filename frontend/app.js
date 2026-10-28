/**
 * MCP Data Assistant - Frontend Application
 * Connects to FastAPI backend at http://127.0.0.1:8200
 * All operations are read-only.
 */

const API = window.location.hostname ? `${window.location.protocol}//${window.location.hostname}:8200` : 'http://127.0.0.1:8200';

// --- LocalStorage Helpers for Chat History ---
const CHAT_HISTORY_KEY = 'mcp_chat_conversations';

function getChatHistoryFromLocalStorage() {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }
  } catch (err) {
    console.warn('Failed to load chat history:', err);
  }
  return [
    { id: 1, text: 'GLS invoice number not filling', time: 'Just now', active: true },
    { id: 2, text: 'POPRINT supplier name issue', time: 'Yesterday', active: false },
    { id: 3, text: 'Why IGST not calculated?', time: 'Yesterday', active: false },
    { id: 4, text: 'Show mapping for GLS Sales', time: '2 days ago', active: false },
    { id: 5, text: 'TURBOMACH dataset info', time: '3 days ago', active: false },
  ];
}

function saveHistoryToLocalStorage() {
  try {
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(state.history));
  } catch (err) {
    console.warn('Failed to save chat history:', err);
  }
}

function loadConversationMessages(id) {
  try {
    const raw = localStorage.getItem('mcp_chat_messages_' + id);
    if (raw) return JSON.parse(raw);
  } catch (err) {
    console.warn('Failed to load conversation messages:', err);
  }

  // Pre-populated placeholder conversations messages
  if (id === 1) {
    return [
      { role: 'user', text: 'Why invoice number not filling?', time: '12:05 PM' },
      { role: 'assistant', data: {
          intent: 'invoice_issue',
          answer: 'I checked the invoice mapping data. The invoice number is not filling mainly because the OCR found the label, but the alias “Invoice No.” is not fully linked to the mapped field.\n\nDetails:\n- Field: Invoice Number\n- Mapped field: sales_form_invoice_no\n- Confidence: 72%\n- Issue: alias mismatch / validation mismatch\n- Expected aliases: Invoice No., Inv No., Invoice #, Rechnungsnummer\n\nSource checked:\n- Dataset: GLS_Sales_Invoice\n- Table: training_mappings\n- Read Only: true\n\nNext step:\nAdd or verify the alias “Invoice No.” in the training mapping before using it for auto-fill.',
          confidence: 72,
          sources: [
            { type: 'Database Table', name: 'training_mappings', record_id: '12', field: 'Invoice Number', source: 'database:training_mappings', confidence: 0.72 }
          ]
      }}
    ];
  }
  if (id === 2) {
    return [
      { role: 'user', text: 'POPRINT purchase order mapping', time: 'Yesterday' },
      { role: 'assistant', data: {
          intent: 'po_query',
          answer: 'I found the PO number mapping in the POPRINT purchase order dataset.\n\nDetails:\n- Field: PO Number\n- Expected format: PO-\\d{4}-\\d+ (e.g., PO-2024-00892)\n- Aliases: Order No., Purchase Order No., PO#\n- Mapped field: po_form_po_number\n- Confidence: 93%\n- Status: Active\n\nSource checked:\n- Dataset: POPRINT_Training\n- Table: training_mappings\n- Read Only: true\n\nNext step:\nUse PO number format PO-\\d{4}-\\d+ when mapping purchase orders.',
          confidence: 93,
          sources: [
            { type: 'Database Table', name: 'training_mappings', record_id: '15', field: 'PO Number', source: 'database:training_mappings', confidence: 0.93 }
          ]
      }}
    ];
  }
  if (id === 3) {
    return [
      { role: 'user', text: 'Why IGST not calculated?', time: 'Yesterday' },
      { role: 'assistant', data: {
          intent: 'mapping_query',
          answer: 'In the connected ERP database, IGST calculation is driven by the state tax group settings. If the customer and supplier states are matching, CGST + SGST is calculated instead of IGST.',
          confidence: 90,
          sources: [
            { type: 'Database Table', name: 'm_customers_t', record_id: '1', field: 'State ID', source: 'database:m_customers_t', confidence: 0.9 }
          ]
      }}
    ];
  }
  return [];
}

function saveConversationMessages(id, messages) {
  try {
    localStorage.setItem('mcp_chat_messages_' + id, JSON.stringify(messages));
  } catch (err) {
    console.warn('Failed to save conversation messages:', err);
  }
}

// --- State -------------------------------------------------------------------
const state = {
  messages: [],
  history: getChatHistoryFromLocalStorage(),
  loading: false,
  overview: null,
  
  // Dashboard routing
  currentView: 'chat',

  // View 2: Datasets cache
  datasets: [],
  selectedDataset: null,
  selectedDatasetRecords: [],

  // View 3: Companies cache
  companies: [],

  // View 4: Mappings cache
  mappings: [],
  mappingsPage: 1,
  mappingsLimit: 7,

  // View 5: Validation Results cache
  validations: [],

  // View 6: Database Overview cache
  dbTables: [],
  selectedDbTable: null,
  selectedDbTableSchema: [],
  selectedDbTableData: [],
  
  // Session memory context
  sessionContext: {
    company: null,
    document_type: null
  }
};

// --- DOM refs -----------------------------------------------------------------
const $ = id => document.getElementById(id);
const chatInput    = $('chatInput');
const sendBtn      = $('sendBtn');
const messageList  = $('messageList');
const welcomeScreen = $('welcomeScreen');
const historyList  = $('historyList');

let activeConversationId = null;

function renderConversationMessages(msgs) {
  messageList.innerHTML = '';
  if (msgs && msgs.length > 0) {
    welcomeScreen.style.display = 'none';
    messageList.classList.remove('hidden');
    msgs.forEach(m => {
      if (m.role === 'user') {
        appendUserMessage(m.text, m.time);
      } else if (m.role === 'assistant') {
        appendAssistantMessage(m.data);
      }
    });
  } else {
    welcomeScreen.style.display = 'flex';
    messageList.classList.add('hidden');
  }
}

// --- Init ---------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  renderHistory();
  
  // Set default active conversation ID on start
  const activeItem = state.history.find(h => h.active);
  if (activeItem) {
    activeConversationId = activeItem.id;
    const msgs = loadConversationMessages(activeConversationId);
    renderConversationMessages(msgs);
  }

  loadOverview();
  loadStatus();
  renderQueryHistory();

  // Auto-resize textarea
  if (chatInput) {
    chatInput.addEventListener('input', () => {
      chatInput.style.height = 'auto';
      chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
    });

    // Send on Enter (Shift+Enter for newline)
    chatInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  if (sendBtn) sendBtn.addEventListener('click', sendMessage);
  if ($('newChatBtn')) $('newChatBtn').addEventListener('click', newChat);
  if ($('historySearch')) $('historySearch').addEventListener('input', e => filterHistory(e.target.value));

  // --- Theme setup ---
  const themeBtn = $('themeBtn');
  const themeSelect = $('settings-theme-select');
  const currentTheme = localStorage.getItem('theme') || 'dark';
  
  const applyTheme = (theme) => {
    if (theme === 'light') {
      document.body.classList.add('light-theme');
      if (themeBtn) themeBtn.textContent = 'Light';
      if (themeSelect) themeSelect.value = 'light';
    } else {
      document.body.classList.remove('light-theme');
      if (themeBtn) themeBtn.textContent = 'Dark';
      if (themeSelect) themeSelect.value = 'dark';
    }
  };

  applyTheme(currentTheme);

  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const isLight = document.body.classList.contains('light-theme');
      const nextTheme = isLight ? 'dark' : 'light';
      localStorage.setItem('theme', nextTheme);
      applyTheme(nextTheme);
    });
  }

  if (themeSelect) {
    themeSelect.addEventListener('change', (e) => {
      const nextTheme = e.target.value;
      localStorage.setItem('theme', nextTheme);
      applyTheme(nextTheme);
    });
  }

  // --- Sidebar toggles ---
  const appShell = $('appShell');
  const toggleLeftSidebar = $('toggleLeftSidebar');
  const toggleRightSidebar = $('toggleRightSidebar');

  // Load saved sidebar states
  if (localStorage.getItem('sidebar-left-collapsed') === 'true') {
    appShell.classList.add('left-collapsed');
  }
  if (localStorage.getItem('sidebar-right-collapsed') === 'true') {
    appShell.classList.add('right-collapsed');
  }

  if (toggleLeftSidebar) {
    toggleLeftSidebar.addEventListener('click', () => {
      appShell.classList.toggle('left-collapsed');
      localStorage.setItem('sidebar-left-collapsed', appShell.classList.contains('left-collapsed'));
    });
  }

  if (toggleRightSidebar) {
    toggleRightSidebar.addEventListener('click', () => {
      appShell.classList.toggle('right-collapsed');
      localStorage.setItem('sidebar-right-collapsed', appShell.classList.contains('right-collapsed'));
    });
  }

  // --- Register Event Listeners for Filters/Search ---
  registerFiltersAndSearch();

  // Periodically refresh status
  setInterval(loadStatus, 30000);
});

// --- Switch Active View (Router) ----------------------------------------------
function switchView(viewName) {
  state.currentView = viewName;

  // 1. Highlight current nav item
  document.querySelectorAll('.sidebar-left .nav-item').forEach(item => {
    item.classList.remove('active');
  });
  
  // Custom mapping for ID
  let navId = 'nav' + viewName.charAt(0).toUpperCase() + viewName.slice(1);
  if (viewName === 'database') navId = 'navDB';
  const activeNavItem = $(navId);
  if (activeNavItem) {
    activeNavItem.classList.add('active');
  }

  // 2. Display the view container
  document.querySelectorAll('.app-view').forEach(view => {
    view.classList.remove('active');
  });
  const activeView = $('view-' + viewName);
  if (activeView) {
    activeView.classList.add('active');
  }

  // 3. Toggle Right Sidebar controller in Topbar (only shown in chat)
  const rightSidebarBtn = $('toggleRightSidebar');
  if (rightSidebarBtn) {
    rightSidebarBtn.style.display = viewName === 'chat' ? 'flex' : 'none';
  }

  // 4. Load data for specific view
  if (viewName === 'datasets') {
    loadDatasetView();
  } else if (viewName === 'companies') {
    loadCompaniesView();
  } else if (viewName === 'mappings') {
    loadMappingsView();
  } else if (viewName === 'validation') {
    loadValidationView();
  } else if (viewName === 'database') {
    loadDatabaseView();
  } else if (viewName === 'status') {
    loadStatusView();
  }
}

// --- Filter Search Handlers Registration -------------------------------------
function registerFiltersAndSearch() {
  // View 2: Datasets
  const dsSearch = $('datasets-search');
  const dsFilterComp = $('datasets-filter-company');
  const dsFilterDoc = $('datasets-filter-doctype');
  const dsClear = $('datasets-clear-filters');

  if (dsSearch) dsSearch.addEventListener('input', renderDatasetsTable);
  if (dsFilterComp) dsFilterComp.addEventListener('change', renderDatasetsTable);
  if (dsFilterDoc) dsFilterDoc.addEventListener('change', renderDatasetsTable);
  if (dsClear) {
    dsClear.addEventListener('click', () => {
      if (dsSearch) dsSearch.value = '';
      if (dsFilterComp) dsFilterComp.value = '';
      if (dsFilterDoc) dsFilterDoc.value = '';
      renderDatasetsTable();
    });
  }

  // View 3: Companies
  const coSearch = $('companies-search');
  const coRefresh = $('companies-refresh-btn');
  if (coSearch) coSearch.addEventListener('input', renderCompaniesTable);
  if (coRefresh) coRefresh.addEventListener('click', loadCompaniesView);

  // View 4: Mappings
  const mapSearch = $('mappings-search');
  const mapFilterComp = $('mappings-filter-company');
  const mapFilterDoc = $('mappings-filter-doctype');
  const mapClear = $('mappings-clear-filters');
  const mapPrev = $('mappings-prev-page');
  const mapNext = $('mappings-next-page');

  if (mapSearch) mapSearch.addEventListener('input', () => { state.mappingsPage = 1; renderMappingsTable(); });
  if (mapFilterComp) mapFilterComp.addEventListener('change', () => { state.mappingsPage = 1; renderMappingsTable(); });
  if (mapFilterDoc) mapFilterDoc.addEventListener('change', () => { state.mappingsPage = 1; renderMappingsTable(); });
  if (mapClear) {
    mapClear.addEventListener('click', () => {
      if (mapSearch) mapSearch.value = '';
      if (mapFilterComp) mapFilterComp.value = '';
      if (mapFilterDoc) mapFilterDoc.value = '';
      state.mappingsPage = 1;
      renderMappingsTable();
    });
  }
  if (mapPrev) {
    mapPrev.addEventListener('click', () => {
      if (state.mappingsPage > 1) {
        state.mappingsPage--;
        renderMappingsTable();
      }
    });
  }
  if (mapNext) {
    mapNext.addEventListener('click', () => {
      const maxPages = Math.ceil(getFilteredMappings().length / state.mappingsLimit);
      if (state.mappingsPage < maxPages) {
        state.mappingsPage++;
        renderMappingsTable();
      }
    });
  }

  // View 5: Validation
  const valSearch = $('validation-search');
  const valRefresh = $('validation-refresh-btn');
  if (valSearch) valSearch.addEventListener('input', renderValidationTable);
  if (valRefresh) valRefresh.addEventListener('click', loadValidationView);

  // View 6: Database Manual Search
  const manualSearchInput = $('manual-db-search-input');
  const manualSearchBtn = $('manual-db-search-btn');
  if (manualSearchBtn) {
    manualSearchBtn.addEventListener('click', performManualDbSearch);
  }
  if (manualSearchInput) {
    manualSearchInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        performManualDbSearch();
      }
    });
  }

  // View 8: Settings category switching
  window.switchSettingsCategory = (cat) => {
    document.querySelectorAll('.settings-nav-item').forEach(item => {
      item.classList.remove('active');
    });
    const activeItem = $('set-nav-' + cat);
    if (activeItem) activeItem.classList.add('active');

    document.querySelectorAll('.settings-section').forEach(sect => {
      sect.classList.remove('active');
    });
    const activeSection = $('set-sect-' + cat);
    if (activeSection) activeSection.classList.add('active');
  };
}

// --- History ------------------------------------------------------------------
function renderHistory(filter = '') {
  const filtered = filter
    ? state.history.filter(h => h.text.toLowerCase().includes(filter.toLowerCase()))
    : state.history;

  historyList.innerHTML = filtered.map(h => `
    <div class="history-item ${h.active ? 'active' : ''}" onclick="loadHistory(${h.id})">
      <span class="hi-icon">Chat</span>
      <span class="hi-text">${escHtml(h.text)}</span>
      <span class="hi-time">${h.time}</span>
    </div>
  `).join('');

  if (filtered.length === 0) {
    historyList.innerHTML = `<div style="padding:12px;font-size:12px;color:var(--text-muted);text-align:center">No conversations found</div>`;
  }
}

function filterHistory(q) { renderHistory(q); }

function loadHistory(id) {
  state.history.forEach(h => h.active = h.id === id);
  saveHistoryToLocalStorage();
  renderHistory();
  activeConversationId = id;
  const msgs = loadConversationMessages(id);
  renderConversationMessages(msgs);
  switchView('chat');
}

function newChat() {
  state.messages = [];
  messageList.innerHTML = '';
  messageList.classList.add('hidden');
  welcomeScreen.style.display = 'flex';
  chatInput.value = '';
  chatInput.style.height = 'auto';

  // Clear session memory context
  state.sessionContext = {
    company: null,
    document_type: null
  };

  const newId = Date.now();
  const newEntry = {
    id: newId,
    text: 'New chat',
    time: 'Just now',
    active: true,
  };
  state.history.forEach(h => h.active = false);
  state.history.unshift(newEntry);
  activeConversationId = newId;
  saveHistoryToLocalStorage();
  renderHistory();
  renderConversationMessages([]);
  switchView('chat');
}

// --- Overview / Status loaders ------------------------------------------------
async function loadOverview() {
  try {
    const res = await fetch(`${API}/api/overview`);
    const data = await res.json();
    state.overview = data;

    // DB card
    const db = data.database || {};
    $('dbTableCount').textContent = db.table_count ?? '-';
    $('dbRecordCount').textContent = (db.total_records ?? '-').toLocaleString?.() ?? db.total_records ?? '-';

    // Chat sidebar Database Overview card name field
    if ($('dbFileName')) {
      $('dbFileName').textContent = db.database_path || 'Real DB path unavailable';
    }

    // Update Database Overview sidebar meta rows too:
    if ($('db-meta-file')) {
      $('db-meta-file').textContent = db.database_path || 'Real DB path unavailable';
    }
    if ($('db-meta-tables')) {
      $('db-meta-tables').textContent = db.table_count ?? '0';
    }
    if ($('db-meta-records')) {
      $('db-meta-records').textContent = (db.total_records ?? '0').toLocaleString?.() ?? db.total_records ?? '0';
    }

    // Dataset card
    const ds = data.datasets || {};
    $('dsTotal').textContent = ds.total_datasets ?? '-';
    $('dsCompanies').textContent = ds.total_companies ?? '-';
    $('dsDocTypes').textContent = ds.total_document_types ?? '-';
    $('dsMappings').textContent = ds.total_mappings ?? '-';

    // Nav counts
    $('navDatasetCount').textContent = ds.total_datasets ?? '-';
    $('navCompanyCount').textContent = ds.total_companies ?? '-';
    $('navMappingCount').textContent = ds.total_mappings ?? '-';
    $('navTableCount').textContent = db.table_count ?? '-';

    // Recent records
    const datasets = ds.datasets || [];
    const recentHTML = datasets.slice(0, 4).map((d, i) => {
      const dotClass = d.company?.toLowerCase() || 'default';
      const times = ['2 mins ago', '15 mins ago', '1 hour ago', '3 hours ago'];
      return `
        <div class="recent-record" onclick="selectDatasetFromSidebar('${escHtml(d.name)}')">
          <div class="rr-dot ${dotClass}"></div>
          <span class="rr-name">${escHtml(d.name)}</span>
          <span class="rr-time">${times[i] || '-'}</span>
        </div>`;
    }).join('');
    $('recentRecords').innerHTML = recentHTML || '<div style="font-size:12px;color:var(--text-muted)">No datasets found</div>';

  } catch (err) {
    console.warn('Overview load failed:', err);
    const errMsg = 'Backend not reachable. Start with run_backend.bat first.';
    ['dbTableCount','dbRecordCount','dbFileName','dsTotal','dsCompanies','dsDocTypes','dsMappings'].forEach(id => {
      const el = $(id); if (el) el.textContent = '-';
    });
    ['navDatasetCount','navCompanyCount','navMappingCount','navTableCount'].forEach(id => {
      const el = $(id); if (el) el.textContent = '-';
    });
    const we = $('welcomeError');
    if (we) {
      we.style.display = 'block';
      we.innerHTML = `<div class="error-banner">Warning ${escHtml(errMsg)}</div>`;
    }
  }
}

async function loadStatus() {
  try {
    const res = await fetch(`${API}/health`);
    const data = await res.json();
    const comps = data.components || {};

    const badge = (status, label) => {
      const cls = status === 'connected' ? 'status-connected'
                : status === 'active'    ? 'status-active'
                : 'status-offline';
      const displayLabel = status === 'connected' ? 'Connected'
                         : status === 'active'    ? 'Active'
                         : status === 'not_available' ? 'Not Running'
                         : 'Error';
      return `<span class="status-badge ${cls}">${label || displayLabel}</span>`;
    };

    const setBadge = (id, status) => {
      const el = $(id);
      if (el) el.innerHTML = badge(status);
    };

    setBadge('statusMCP', comps.mcp_server);
    setBadge('statusDB', comps.database);
    setBadge('statusDS', comps.dataset_storage);
    setBadge('statusRO', 'active');
    setBadge('statusOllama', comps.ollama);
    
    const ut = $('statusUptime');
    if (ut) ut.textContent = data.uptime_human || '-';

    // Populate System Status view elements:
    if ($('sys-status-api')) {
      $('sys-status-api').textContent = 'Online';
      $('sys-status-api').className = 'ssr-status online';
    }
    if ($('sys-status-db')) {
      $('sys-status-db').textContent = comps.database === 'connected' ? 'Connected' : 'Offline';
      $('sys-status-db').className = `ssr-status ${comps.database === 'connected' ? 'online' : 'offline'}`;
    }
    if ($('sys-status-ds')) {
      $('sys-status-ds').textContent = comps.dataset_storage === 'connected' ? 'Connected' : 'Offline';
      $('sys-status-ds').className = `ssr-status ${comps.dataset_storage === 'connected' ? 'online' : 'offline'}`;
    }
    if ($('sys-status-ollama')) {
      $('sys-status-ollama').textContent = comps.ollama === 'connected' ? 'Active' : 'Offline';
      $('sys-status-ollama').className = `ssr-status ${comps.ollama === 'connected' ? 'online' : 'offline'}`;
    }
    if ($('sys-health-uptime')) {
      $('sys-health-uptime').textContent = data.uptime_human || '-';
    }

    // Populate new Environment Properties in System Status view:
    if ($('sys-env-mcp-mode')) {
      $('sys-env-mcp-mode').textContent = data.mcp_mode || 'unknown';
    }
    if ($('sys-env-db-connected')) {
      $('sys-env-db-connected').textContent = data.connected ? 'Yes' : 'No';
    }
    if ($('sys-env-db-file')) {
      $('sys-env-db-file').textContent = data.db_file_name || '-';
    }
    if ($('sys-env-demo-active')) {
      $('sys-env-demo-active').textContent = data.demo_data_active ? 'Yes' : 'No';
    }
    if ($('sys-env-table-count')) {
      $('sys-env-table-count').textContent = data.table_count ?? 0;
    }
    if ($('sys-env-records-count')) {
      $('sys-env-records-count').textContent = data.total_records ?? 0;
    }
    if ($('sys-env-dataset-folder')) {
      $('sys-env-dataset-folder').textContent = (data.dataset_folder_status || '-').toUpperCase();
    }
    if ($('sys-env-import-registry')) {
      $('sys-env-import-registry').textContent = (data.import_registry_status || '-').toUpperCase();
    }
    if ($('sys-env-readonly')) {
      $('sys-env-readonly').textContent = data.read_only_mode ? 'Active' : 'Disabled';
      $('sys-env-readonly').className = data.read_only_mode ? 'dr-value text-success' : 'dr-value text-danger';
    }
    if ($('sys-env-mcp-tools')) {
      $('sys-env-mcp-tools').textContent = data.mcp_tools_count || '0';
    }

    // Update Database Overview card/status metadata:
    if ($('db-conn-status')) {
      $('db-conn-status').textContent = comps.database === 'connected' ? 'Connected Securely' : 'Disconnected';
      $('db-conn-status').className = `connection-status-badge ${comps.database === 'connected' ? '' : 'offline'}`;
    }
    if ($('db-meta-mode')) {
      $('db-meta-mode').textContent = (data.mcp_mode || 'unknown').toUpperCase();
    }
    if ($('db-meta-connected')) {
      $('db-meta-connected').textContent = data.connected ? 'Yes' : 'No';
    }
    if ($('db-meta-file')) {
      $('db-meta-file').textContent = data.db_file_name || '-';
    }
    if ($('db-meta-demo-active')) {
      $('db-meta-demo-active').textContent = data.demo_data_active ? 'Yes' : 'No';
    }
    if ($('db-meta-tables')) {
      $('db-meta-tables').textContent = data.table_count ?? 0;
    }
    if ($('db-meta-records')) {
      $('db-meta-records').textContent = data.total_records ?? 0;
    }
    if ($('db-meta-dataset-folder')) {
      $('db-meta-dataset-folder').textContent = (data.dataset_folder_status || '-').toUpperCase();
    }
    if ($('db-meta-import-registry')) {
      $('db-meta-import-registry').textContent = (data.import_registry_status || '-').toUpperCase();
    }

    // Update Real MCP Server Card
    const mcpServer = data.mcp_server || {};
    const mcpStatusEl = $('mcpRealStatus');
    if (mcpStatusEl) {
      if (data.mcp_server_enabled !== undefined) {
        mcpStatusEl.innerHTML = badge(data.mcp_server_enabled ? 'connected' : 'offline', data.mcp_server_enabled ? 'Enabled' : 'Disabled');
      } else {
        mcpStatusEl.innerHTML = `<span class="status-badge status-offline">Unavailable</span>`;
      }
    }
    
    const mcpTransportEl = $('mcpRealTransport');
    if (mcpTransportEl) {
      mcpTransportEl.textContent = mcpServer.transport || data.mcp_server_transport || 'Unavailable';
    }
    
    const mcpToolsCountEl = $('mcpRealToolsCount');
    if (mcpToolsCountEl) {
      mcpToolsCountEl.textContent = (mcpServer.tools_count !== undefined) ? mcpServer.tools_count : 
                                    (data.mcp_server_tools_count !== undefined) ? data.mcp_server_tools_count : 'Unavailable';
    }

    // Update Ollama Card
    const ollamaInfo = data.ollama || {};
    const ollamaStatusEl = $('ollamaRealStatus');
    if (ollamaStatusEl) {
      if (data.ollama_enabled !== undefined) {
        const ollamaActive = data.ollama_available || ollamaInfo.available;
        ollamaStatusEl.innerHTML = badge(ollamaActive ? 'active' : 'offline', ollamaActive ? 'Active' : 'Offline');
      } else {
        ollamaStatusEl.innerHTML = `<span class="status-badge status-offline">Not Configured</span>`;
      }
    }

    const ollamaModelEl = $('ollamaRealModel');
    if (ollamaModelEl) {
      ollamaModelEl.textContent = ollamaInfo.model || data.ollama_model || 'Unavailable';
    }

    const ollamaTimeoutEl = $('ollamaRealTimeout');
    if (ollamaTimeoutEl) {
      const timeoutVal = ollamaInfo.timeout_seconds || data.ollama_timeout_seconds;
      ollamaTimeoutEl.textContent = timeoutVal !== undefined ? `${timeoutVal}s` : 'Unavailable';
    }

    // Control Warning Banner for Real Database Missing
    const warningBanner = $('dbMissingWarningBanner');
    if (warningBanner) {
      if (data.mcp_mode === 'real' && !data.connected) {
        warningBanner.style.display = 'block';
      } else {
        warningBanner.style.display = 'none';
      }
    }

  } catch (err) {
    ['statusMCP','statusDB','statusDS','statusRO','statusOllama'].forEach(id => {
      const el = $(id);
      if (el) el.innerHTML = '<span class="status-badge status-offline">Offline</span>';
    });
    ['mcpRealStatus', 'ollamaRealStatus'].forEach(id => {
      const el = $(id);
      if (el) el.innerHTML = '<span class="status-badge status-offline">Offline</span>';
    });
    ['mcpRealTransport', 'mcpRealToolsCount', 'ollamaRealModel', 'ollamaRealTimeout'].forEach(id => {
      const el = $(id);
      if (el) el.textContent = 'Unavailable';
    });
    const ut = $('statusUptime');
    if (ut) ut.textContent = '-';
  }
}

// --- 2. DATASET EXPLORER LOGIC ------------------------------------------------
async function loadDatasetView() {
  try {
    // Populate stats from overview state if loaded
    if (state.overview && state.overview.datasets) {
      const ds = state.overview.datasets;
      $('datasets-metric-total').textContent = ds.total_datasets ?? 0;
      $('datasets-metric-records').textContent = ds.total_records ?? 0;
      $('datasets-metric-companies').textContent = ds.total_companies ?? 0;
      $('datasets-metric-mappings').textContent = ds.total_mappings ?? 0;

      // Populate filter dropdowns
      const compSelect = $('datasets-filter-company');
      const docSelect = $('datasets-filter-doctype');
      
      if (compSelect && compSelect.options.length <= 1) {
        (ds.companies || []).forEach(c => {
          compSelect.add(new Option(c, c));
        });
      }
      if (docSelect && docSelect.options.length <= 1) {
        (ds.document_types || []).forEach(d => {
          docSelect.add(new Option(d, d));
        });
      }
    }

    const res = await fetch(`${API}/api/datasets`);
    const data = await res.json();
    
    // Merge directory files with metadata to get counts
    const metaList = (state.overview && state.overview.datasets && state.overview.datasets.datasets) || [];
    state.datasets = (data.datasets || []).map(d => {
      const match = metaList.find(m => m.name === d.name);
      return {
        ...d,
        company: match ? match.company : 'ALL',
        document_type: match ? match.document_type : 'Mapping',
        record_count: match ? match.record_count : 0
      };
    });

    renderDatasetsTable();
  } catch (err) {
    console.error('Dataset load error:', err);
    $('datasets-table').querySelector('tbody').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--danger)">Failed to load datasets. ${err.message}</td></tr>`;
  }
}

function renderDatasetsTable() {
  const tableBody = $('datasets-table').querySelector('tbody');
  const q = ($('datasets-search')?.value || '').toLowerCase();
  const filterComp = $('datasets-filter-company')?.value;
  const filterDoc = $('datasets-filter-doctype')?.value;

  const filtered = state.datasets.filter(d => {
    const matchesQ = d.name.toLowerCase().includes(q) || d.company.toLowerCase().includes(q) || d.document_type.toLowerCase().includes(q);
    const matchesComp = !filterComp || d.company === filterComp;
    const matchesDoc = !filterDoc || d.document_type === filterDoc;
    return matchesQ && matchesComp && matchesDoc;
  });

  tableBody.innerHTML = filtered.map(d => `
    <tr>
      <td><strong>${escHtml(d.name)}</strong></td>
      <td><span class="badge badge-rule">${escHtml(d.company)}</span></td>
      <td>${escHtml(d.document_type)}</td>
      <td>${d.record_count} records</td>
      <td>${formatBytes(d.size_bytes)}</td>
      <td><code>${escHtml(d.source)}</code></td>
      <td><a class="row-action-link" onclick="selectDataset('${escHtml(d.name)}')">View Details</a></td>
    </tr>
  `).join('');

  if (filtered.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-secondary)">No datasets match the filters.</td></tr>`;
  }
}

async function selectDataset(name) {
  try {
    $('dataset-record-preview').innerHTML = `<span style="color:var(--text-muted)">Fetching dataset details...</span>`;
    
    const res = await fetch(`${API}/api/datasets/${name}`);
    const data = await res.json();
    state.selectedDataset = name;
    state.selectedDatasetRecords = data.records || [];

    // JSON Record Preview (First Record)
    const previewContainer = $('dataset-record-preview');
    if (state.selectedDatasetRecords.length > 0) {
      previewContainer.innerHTML = highlightJson(state.selectedDatasetRecords[0]);
    } else {
      previewContainer.innerHTML = `<span style="color:var(--text-muted)">Empty Dataset (No records found)</span>`;
    }

    // Populate Details Card
    const meta = data.meta || {};
    $('ds-details-name').textContent = meta.name || name;
    $('ds-details-company').textContent = meta.company || 'ALL';
    $('ds-details-doctype').textContent = meta.document_type || '-';
    $('ds-details-records').textContent = data.count ?? 0;
    
    const matchFile = state.datasets.find(d => d.name === name);
    $('ds-details-ext').textContent = matchFile ? matchFile.extension.toUpperCase().slice(1) : 'JSON';
    $('ds-details-updated').textContent = meta.last_updated ? meta.last_updated.split(' ')[0] : 'Just now';

    // Calculate Average Confidence
    const confs = (data.records || []).map(r => r.confidence).filter(c => c != null);
    let avgConfStr = '-';
    if (confs.length > 0) {
      const avg = confs.reduce((a, b) => a + b, 0) / confs.length;
      avgConfStr = `${Math.round(avg > 1 ? avg : avg * 100)}%`;
    }
    const confEl = $('ds-details-confidence');
    if (confEl) confEl.textContent = avgConfStr;

    const actionBtn = $('ds-view-full-btn');
    actionBtn.disabled = false;
    actionBtn.onclick = () => {
      quickSearch(`Show ${name} dataset`);
      switchView('chat');
    };
  } catch (err) {
    console.error('Select dataset error:', err);
    $('dataset-record-preview').textContent = `Error loading details: ${err.message}`;
  }
}

function selectDatasetFromSidebar(name) {
  switchView('datasets');
  setTimeout(() => selectDataset(name), 100);
}

// --- 3. COMPANIES LOGIC ------------------------------------------------------
async function loadCompaniesView() {
  try {
    // Make sure datasets and mappings are loaded to compute counts
    if (state.datasets.length === 0) {
      const dsRes = await fetch(`${API}/api/datasets`);
      const dsData = await dsRes.json();
      const metaList = (state.overview && state.overview.datasets && state.overview.datasets.datasets) || [];
      state.datasets = (dsData.datasets || []).map(d => {
        const match = metaList.find(m => m.name === d.name);
        return {
          ...d,
          company: match ? match.company : 'ALL',
          document_type: match ? match.document_type : 'Mapping',
          record_count: match ? match.record_count : 0
        };
      });
    }
    if (state.mappings.length === 0) {
      const mapRes = await fetch(`${API}/api/db/tables/training_mappings/search?q=&limit=100`);
      const mapData = await mapRes.json();
      state.mappings = mapData.records || [];
    }

    const res = await fetch(`${API}/api/db/tables/companies/search?q=&limit=100`);
    const data = await res.json();
    if (data.error) {
      state.companies = [];
      $('companies-table').querySelector('tbody').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">Companies view is not backed by a table in the connected ERP database (real-mode has no "companies" table). No data to show.</td></tr>`;
      return;
    }
    state.companies = data.records || [];
    renderCompaniesTable();
  } catch (err) {
    console.error('Companies load error:', err);
    $('companies-table').querySelector('tbody').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--danger)">Failed to load companies from SQLite. ${err.message}</td></tr>`;
  }
}

function renderCompaniesTable() {
  const tableBody = $('companies-table').querySelector('tbody');
  const q = ($('companies-search')?.value || '').toLowerCase();

  const filtered = state.companies.filter(c => {
    return c.code.toLowerCase().includes(q) || 
           c.name.toLowerCase().includes(q) || 
           (c.country || '').toLowerCase().includes(q) || 
           (c.industry || '').toLowerCase().includes(q);
  });

  tableBody.innerHTML = filtered.map(c => {
    // Count datasets matching this company
    const datasetsCount = state.datasets.filter(d => d.company === c.code).length;
    
    // Count mappings matching this company
    const mappingsCount = state.mappings.filter(m => m.company_code === c.code).length;
    
    // Get unique document types from mappings and datasets
    const docTypesList = Array.from(new Set([
      ...state.mappings.filter(m => m.company_code === c.code).map(m => m.document_type),
      ...state.datasets.filter(d => d.company === c.code).map(d => d.document_type)
    ])).filter(Boolean);
    const docTypesStr = docTypesList.length > 0 ? docTypesList.join(', ') : '-';

    return `
      <tr>
        <td>${c.id}</td>
        <td><strong>${escHtml(c.code)}</strong></td>
        <td>${escHtml(c.name)}</td>
        <td><span class="badge badge-rule">${datasetsCount}</span></td>
        <td><span class="badge badge-ollama">${mappingsCount}</span></td>
        <td style="font-size:12px;color:var(--text-muted)">${escHtml(docTypesStr)}</td>
        <td><span class="badge-row-status ${c.active ? 'success' : 'danger'}">${c.active ? 'Active' : 'Inactive'}</span></td>
      </tr>
    `;
  }).join('');

  if (filtered.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-secondary)">No companies found.</td></tr>`;
  }
}

// --- 4. FIELD MAPPINGS LOGIC -------------------------------------------------
async function loadMappingsView() {
  try {
    const res = await fetch(`${API}/api/db/tables/training_mappings/search?q=&limit=100`);
    const data = await res.json();
    if (data.error) {
      state.mappings = [];
      $('mappings-table').querySelector('tbody').innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">Field Mappings view is not backed by a table in the connected ERP database (real-mode has no "training_mappings" table). No data to show.</td></tr>`;
      return;
    }
    state.mappings = data.records || [];

    // Populate mappings company/doc type dropdown filters dynamically
    const mapFilterComp = $('mappings-filter-company');
    const mapFilterDoc = $('mappings-filter-doctype');

    if (mapFilterComp && mapFilterComp.options.length <= 1) {
      const companiesList = Array.from(new Set(state.mappings.map(m => m.company_code)));
      companiesList.forEach(c => {
        mapFilterComp.add(new Option(c, c));
      });
    }
    if (mapFilterDoc && mapFilterDoc.options.length <= 1) {
      const docList = Array.from(new Set(state.mappings.map(m => m.document_type)));
      docList.forEach(d => {
        mapFilterDoc.add(new Option(d, d));
      });
    }

    renderMappingsTable();
  } catch (err) {
    console.error('Mappings load error:', err);
    $('mappings-table').querySelector('tbody').innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--danger)">Failed to load field mappings from SQLite. ${err.message}</td></tr>`;
  }
}

function getFilteredMappings() {
  const q = ($('mappings-search')?.value || '').toLowerCase();
  const filterComp = $('mappings-filter-company')?.value;
  const filterDoc = $('mappings-filter-doctype')?.value;

  return state.mappings.filter(m => {
    const matchesQ = m.field_name.toLowerCase().includes(q) || 
                     m.mapped_to.toLowerCase().includes(q) || 
                     (m.aliases || '').toLowerCase().includes(q);
    const matchesComp = !filterComp || m.company_code === filterComp;
    const matchesDoc = !filterDoc || m.document_type === filterDoc;
    return matchesQ && matchesComp && matchesDoc;
  });
}

function renderMappingsTable() {
  const tableBody = $('mappings-table').querySelector('tbody');
  const filtered = getFilteredMappings();

  // Pagination bounds
  const total = filtered.length;
  const limit = state.mappingsLimit;
  const maxPages = Math.ceil(total / limit) || 1;
  if (state.mappingsPage > maxPages) state.mappingsPage = maxPages;
  
  const start = (state.mappingsPage - 1) * limit;
  const end = Math.min(start + limit, total);
  
  const pageData = filtered.slice(start, end);

  // Render rows
  tableBody.innerHTML = pageData.map(m => {
    const confPct = Math.round((m.confidence || 0) * 100);
    let confClass = 'badge-conf-low';
    if (confPct >= 80) confClass = 'badge-conf-high';
    else if (confPct >= 60) confClass = 'badge-conf-medium';

    return `
      <tr>
        <td>${m.id}</td>
        <td><strong>${escHtml(m.field_name)}</strong></td>
        <td><code>${escHtml(m.mapped_to)}</code></td>
        <td><span class="badge badge-rule">${escHtml(m.company_code)}</span></td>
        <td>${escHtml(m.document_type)}</td>
        <td style="font-size:12px;color:var(--text-muted);max-width:300px;text-overflow:ellipsis;overflow:hidden;white-space:nowrap" title="${escHtml(m.aliases)}">
          ${escHtml((m.aliases || '').replace(/\|/g, ', '))}
        </td>
        <td><span class="badge ${confClass}">${confPct}%</span></td>
        <td><span class="badge-row-status ${m.status === 'active' ? 'success' : 'danger'}">${escHtml(m.status)}</span></td>
      </tr>
    `;
  }).join('');

  if (total === 0) {
    tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-secondary)">No mappings found.</td></tr>`;
  }

  // Update pagination footer
  $('mappings-pagination-info').textContent = total > 0 
    ? `Showing ${start + 1} to ${end} of ${total} mappings`
    : `Showing 0 to 0 of 0 mappings`;

  $('mappings-prev-page').disabled = state.mappingsPage <= 1;
  $('mappings-next-page').disabled = state.mappingsPage >= maxPages;
}

// --- 5. VALIDATION RESULTS LOGIC ---------------------------------------------
async function loadValidationView() {
  try {
    const res = await fetch(`${API}/api/db/tables/validation_results/search?q=&limit=100`);
    const data = await res.json();
    if (data.error) {
      state.validations = [];
      $('validation-table').querySelector('tbody').innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--text-muted)">Validation Results view is not backed by a table in the connected ERP database (real-mode has no "validation_results" table). No data to show.</td></tr>`;
      return;
    }
    state.validations = data.records || [];

    // Calculate metrics
    const total = state.validations.length;
    const passed = state.validations.filter(v => v.validation_status === 'PASS').length;
    const failed = state.validations.filter(v => v.validation_status === 'FAIL').length;
    const warnings = state.validations.filter(v => v.validation_status !== 'PASS' && v.validation_status !== 'FAIL').length;

    $('val-metric-total').textContent = total;
    $('val-metric-passed').textContent = passed;
    $('val-metric-warnings').textContent = warnings;
    $('val-metric-failed').textContent = failed;

    // Calculate low confidence fields
    const failedItems = state.validations.filter(v => v.validation_status === 'FAIL' || (v.confidence != null && v.confidence < 0.5));
    const lowConfidenceFields = failedItems.length > 0 
      ? Array.from(new Set(failedItems.map(v => v.field_name))).filter(Boolean).join(', ')
      : 'None';
    const lowConfEl = $('val-metric-low-confidence');
    if (lowConfEl) lowConfEl.textContent = lowConfidenceFields;

    renderValidationTable();
  } catch (err) {
    console.error('Validation load error:', err);
    $('validation-table').querySelector('tbody').innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--danger)">Failed to load validation results from SQLite. ${err.message}</td></tr>`;
  }
}

function renderValidationTable() {
  const tableBody = $('validation-table').querySelector('tbody');
  const q = ($('validation-search')?.value || '').toLowerCase();

  const filtered = state.validations.filter(v => {
    return v.upload_id.toLowerCase().includes(q) || 
           (v.company_code || '').toLowerCase().includes(q) || 
           (v.document_type || '').toLowerCase().includes(q) ||
           v.field_name.toLowerCase().includes(q) ||
           (v.extracted_value || '').toLowerCase().includes(q);
  });

  tableBody.innerHTML = filtered.map(v => {
    const isPass = v.validation_status === 'PASS';
    const statusClass = isPass ? 'success' : v.validation_status === 'FAIL' ? 'danger' : 'warning';
    const confPct = Math.round((v.confidence || 0) * 100);

    return `
      <tr>
        <td>${v.id}</td>
        <td><code>${escHtml(v.upload_id)}</code></td>
        <td><strong>${escHtml(v.company_code || '-')}</strong></td>
        <td>${escHtml(v.document_type || '-')}</td>
        <td>${escHtml(v.field_name)}</td>
        <td><code>${escHtml(v.extracted_value || '-')}</code></td>
        <td style="font-family:var(--mono);font-size:11.5px;color:var(--text-muted)">${escHtml(v.expected_pattern || '-')}</td>
        <td>${confPct}%</td>
        <td><span class="badge-row-status ${statusClass}">${escHtml(v.validation_status)}</span></td>
        <td style="font-size:12px;color:var(--danger);max-width:250px;word-break:break-word" title="${escHtml(v.failure_reason)}">
          ${escHtml(v.failure_reason || '-')}
        </td>
      </tr>
    `;
  }).join('');

  if (filtered.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--text-secondary)">No validation logs found.</td></tr>`;
  }
}

// --- 6. DATABASE OVERVIEW LOGIC ----------------------------------------------
async function loadDatabaseView() {
  try {
    const res = await fetch(`${API}/api/db/tables`);
    const data = await res.json();
    state.dbTables = data.tables || [];

    renderDbTablesNav(state.dbTables);

    // Select the first table by default
    if (state.dbTables.length > 0) {
      selectDbTable(state.dbTables[0]);
    }
  } catch (err) {
    console.error('DB Tables load error:', err);
    $('db-tables-nav-list').innerHTML = `<div style="padding:10px;color:var(--danger)">Offline</div>`;
  }
}

function renderDbTablesNav(tableNames) {
  const sidebarList = $('db-tables-nav-list');
  const tableCounts = (state.overview && state.overview.database && state.overview.database.tables) || [];

  if (!tableNames || tableNames.length === 0) {
    sidebarList.innerHTML = `<div style="padding:10px;color:var(--text-muted)">No matching tables</div>`;
    return;
  }

  sidebarList.innerHTML = tableNames.map(t => {
    const cntMatch = tableCounts.find(c => c.table === t);
    const cnt = cntMatch ? cntMatch.record_count : 0;
    return `
      <div class="db-tables-nav-item" id="db-nav-tbl-${t}" onclick="selectDbTable('${t}')">
        <span>Sources ${escHtml(t)}</span>
        <span class="tbl-badge">${cnt}</span>
      </div>
    `;
  }).join('');
}

function filterDbTablesList(query) {
  const q = (query || '').toLowerCase().trim();
  const filtered = !q ? state.dbTables : state.dbTables.filter(t => t.toLowerCase().includes(q));
  renderDbTablesNav(filtered);
}

async function selectDbTable(tableName) {
  try {
    state.selectedDbTable = tableName;
    
    // Highlight sidebar
    document.querySelectorAll('.db-tables-nav-item').forEach(item => {
      item.classList.remove('active');
    });
    const activeItem = $('db-nav-tbl-' + tableName);
    if (activeItem) activeItem.classList.add('active');

    $('db-current-table-name').textContent = tableName;
    $('db-schema-table').querySelector('tbody').innerHTML = `<tr><td colspan="5" class="loading-td"><div class="skeleton-row"></div></td></tr>`;
    $('db-data-preview-table').innerHTML = `<tbody><tr><td class="loading-td"><div class="skeleton-row"></div></td></tr></tbody>`;

    // Fetch schema details
    const schemaRes = await fetch(`${API}/api/db/tables/${tableName}/schema`);
    const schemaData = await schemaRes.json();
    state.selectedDbTableSchema = schemaData.columns || [];

    // Fetch rows sample (dedicated read-only sample endpoint)
    const dataRes = await fetch(`${API}/api/db/tables/${tableName}/sample?limit=5`);
    const dataDetails = await dataRes.json();
    state.selectedDbTableData = dataDetails.records || [];

    // Render Schema details table
    const schemaBody = $('db-schema-table').querySelector('tbody');
    schemaBody.innerHTML = state.selectedDbTableSchema.map(col => `
      <tr>
        <td><code>${col.cid}</code></td>
        <td><strong>${escHtml(col.name)}</strong></td>
        <td><code>${escHtml(col.type)}</code></td>
        <td>${col.notnull ? 'Fail Not Null' : 'OK Yes'}</td>
        <td>${col.pk ? 'Key Primary Key' : '-'}</td>
      </tr>
    `).join('');

    // Update row counts badge
    const tableCounts = (state.overview && state.overview.database && state.overview.database.tables) || [];
    const cntMatch = tableCounts.find(c => c.table === tableName);
    const totalRecords = cntMatch ? cntMatch.record_count : (state.selectedDbTableData.length);
    $('db-current-table-records').textContent = `${totalRecords} rows`;
    $('db-current-table-meta').textContent = `SQLite table schema for ${tableName} (${state.selectedDbTableSchema.length} columns)`;

    // Render sample data table
    const dataTable = $('db-data-preview-table');
    if (state.selectedDbTableData.length > 0) {
      const headers = Object.keys(state.selectedDbTableData[0]);
      
      const headHtml = `<thead><tr>${headers.map(h => `<th>${escHtml(h)}</th>`).join('')}</tr></thead>`;
      
      const rowsHtml = `<tbody>${state.selectedDbTableData.map(row => `
        <tr>${headers.map(h => {
          const val = row[h];
          const displayVal = typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val ?? 'NULL');
          return `<td>${escHtml(displayVal)}</td>`;
        }).join('')}</tr>
      `).join('')}</tbody>`;

      dataTable.innerHTML = headHtml + rowsHtml;
    } else {
      dataTable.innerHTML = `<tbody><tr><td style="color:var(--text-secondary);text-align:center">No data records inside this table.</td></tr></tbody>`;
    }

  } catch (err) {
    console.error('Select DB Table error:', err);
    $('db-schema-table').querySelector('tbody').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--danger)">Failed to load table details: ${err.message}</td></tr>`;
  }
}

// --- 7. SYSTEM STATUS VIEW ---------------------------------------------------
async function loadStatusView() {
  try {
    const res = await fetch(`${API}/health`);
    const data = await res.json();
    const comps = data.components || {};

    const updateStatus = (id, status) => {
      const el = $(id);
      if (el) {
        el.textContent = status === 'connected' ? 'Online' : status === 'active' ? 'Active' : 'Offline';
        el.className = `ssr-status ${status === 'connected' || status === 'active' ? 'online' : 'offline'}`;
      }
    };

    updateStatus('sys-status-api', 'connected');
    updateStatus('sys-status-db', comps.database);
    updateStatus('sys-status-ds', comps.dataset_storage);
    updateStatus('sys-status-ollama', comps.ollama === 'connected' ? 'active' : 'offline');

    $('sys-health-uptime').textContent = data.uptime_human || '-';

  } catch (err) {
    console.error('Status view error:', err);
  }
}

// --- Settings Logic (View 8) -------------------------------------------------
function loadSettingsView() {
  const currentTheme = localStorage.getItem('theme') || 'dark';
  const themeSelect = $('settings-theme-select');
  if (themeSelect) themeSelect.value = currentTheme;
}

// --- Chat ---------------------------------------------------------------------
const QUERY_HISTORY_KEY = 'mcp_query_history';
const QUERY_HISTORY_MAX = 20;

function getQueryHistory() {
  try {
    const raw = localStorage.getItem(QUERY_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    return [];
  }
}

function saveQueryToHistory(question) {
  const q = (question || '').trim();
  if (!q) return;
  try {
    let list = getQueryHistory();
    list = list.filter(item => item.text !== q);
    list.unshift({ text: q, time: new Date().toISOString() });
    if (list.length > QUERY_HISTORY_MAX) list = list.slice(0, QUERY_HISTORY_MAX);
    localStorage.setItem(QUERY_HISTORY_KEY, JSON.stringify(list));
  } catch (err) {
    console.warn('Query history save failed:', err);
  }
  renderQueryHistory();
}

function renderQueryHistory() {
  const container = $('queryHistoryList');
  if (!container) return;
  const list = getQueryHistory();

  if (list.length === 0) {
    container.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:6px 0">No queries yet</div>';
    return;
  }

  container.innerHTML = list.map((item, idx) => `
    <div class="query-history-item" style="display:flex;align-items:center;justify-content:space-between;gap:6px;padding:6px 0;border-bottom:1px solid var(--border);cursor:pointer" onclick="rerunHistoryQuery(${idx})" title="Click to rerun this query">
      <span style="font-size:12px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">${escHtml(item.text)}</span>
    </div>
  `).join('');
}

function rerunHistoryQuery(idx) {
  const list = getQueryHistory();
  const item = list[idx];
  if (!item) return;
  switchView('chat');
  quickSearch(item.text);
}

function clearQueryHistory() {
  try {
    localStorage.removeItem(QUERY_HISTORY_KEY);
  } catch (err) {
    console.warn('Query history clear failed:', err);
  }
  renderQueryHistory();
}

async function sendMessage() {
  const question = chatInput.value.trim();
  if (!question || state.loading) return;

  // Ensure we have an active conversation ID
  if (!activeConversationId) {
    const activeItem = state.history.find(h => h.active);
    if (activeItem) {
      activeConversationId = activeItem.id;
    } else if (state.history.length > 0) {
      activeConversationId = state.history[0].id;
      state.history[0].active = true;
      saveHistoryToLocalStorage();
      renderHistory();
    } else {
      activeConversationId = Date.now();
      state.history.push({ id: activeConversationId, text: 'New chat', time: 'Just now', active: true });
      saveHistoryToLocalStorage();
      renderHistory();
    }
  }

  // Context parsing for temporary session memory
  const qLower = question.toLowerCase();
  let companyFound = null;
  if (qLower.includes('gls')) companyFound = 'GLS';
  else if (qLower.includes('poprint')) companyFound = 'POPRINT';
  else if (qLower.includes('turbomach') || qLower.includes('turbo')) companyFound = 'TURBOMACH';
  else if (qLower.includes('mde')) companyFound = 'MDE';
  else if (qLower.includes('alphalog')) companyFound = 'ALPHALOG';
  
  let docTypeFound = null;
  if (qLower.includes('invoice') || qLower.includes('rechnung')) docTypeFound = 'Sales Invoice';
  else if (qLower.includes('purchase order') || qLower.includes('po')) docTypeFound = 'Purchase Order';
  else if (qLower.includes('work order') || qLower.includes('wo')) docTypeFound = 'Work Order';

  if (companyFound) state.sessionContext.company = companyFound;
  if (docTypeFound) state.sessionContext.document_type = docTypeFound;

  // Show chat, hide welcome
  welcomeScreen.style.display = 'none';
  messageList.classList.remove('hidden');

  // Append user message
  const userTime = appendUserMessage(question);
  saveQueryToHistory(question);

  // Save user message to active conversation
  const msgs = loadConversationMessages(activeConversationId) || [];
  msgs.push({ role: 'user', text: question, time: userTime });
  saveConversationMessages(activeConversationId, msgs);

  // Update history item title if it is default "New chat"
  const activeItem = state.history.find(h => h.id === activeConversationId);
  if (activeItem && activeItem.text === 'New chat') {
    activeItem.text = question.slice(0, 40) + (question.length > 40 ? '...' : '');
    saveHistoryToLocalStorage();
    renderHistory();
  }

  chatInput.value = '';
  chatInput.style.height = 'auto';
  state.loading = true;
  sendBtn.disabled = true;

  // Typing indicator
  const typingId = appendTypingIndicator();

  try {
    const res = await fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        company: state.sessionContext.company,
        document_type: state.sessionContext.document_type
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    removeElement(typingId);
    appendAssistantMessage(data);

    // Save assistant response to active conversation
    const currentMsgs = loadConversationMessages(activeConversationId) || [];
    currentMsgs.push({ role: 'assistant', data: data });
    saveConversationMessages(activeConversationId, currentMsgs);

    // Dynamic Overview refresh when data is discussed (e.g. system status, companies, mappings overview)
    setTimeout(loadOverview, 2000);

  } catch (err) {
    removeElement(typingId);
    appendErrorMessage(err.message.includes('fetch') 
      ? 'Backend not reachable. Make sure backend is running on port 8200.'
      : `Error: ${err.message}`);
  } finally {
    state.loading = false;
    sendBtn.disabled = false;
  }
}

function quickSearch(text) {
  if (text === 'Enter exact invoice number') {
    if (chatInput) {
      chatInput.value = '';
      chatInput.placeholder = 'TVL25000001';
      chatInput.focus();
    }
    return;
  }
  chatInput.value = text;
  chatInput.dispatchEvent(new Event('input'));
  sendMessage();
}

// --- Message renderers --------------------------------------------------------
function appendUserMessage(text, time) {
  const now = time || new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  const div = document.createElement('div');
  div.className = 'msg-user fade-in';
  div.innerHTML = `
    <div>
      <div class="bubble">${escHtml(text)}</div>
      <div class="meta">${now} OKOK</div>
    </div>`;
  messageList.appendChild(div);
  scrollBottom();
  return now;
}

function appendTypingIndicator() {
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.className = 'msg-assistant fade-in';
  div.id = id;
  div.innerHTML = `
    <div class="avatar">AI</div>
    <div class="msg-body">
      <div class="msg-name">Data Assistant</div>
      <div class="bubble">
        <div class="typing-indicator">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <span style="font-size:12px;color:var(--text-muted);margin-left:6px">Searching database &amp; datasets...</span>
        </div>
      </div>
    </div>`;
  messageList.appendChild(div);
  scrollBottom();
  return id;
}

function appendAssistantMessage(data) {
  const div = document.createElement('div');
  div.className = 'msg-assistant fade-in';

  const answerHtml = renderMarkdown(data.answer || '');
  const nextHtml = data.next_suggestion
    ? `<div class="next-suggestion"><strong>Suggestion:</strong> ${escHtml(data.next_suggestion)}</div>`
    : '';

  // 1. Greeting response check
  if (data.intent === 'greeting') {
    div.innerHTML = `
      <div class="avatar">AI</div>
      <div class="msg-body">
        <div class="msg-name">Data Assistant</div>
        <div class="bubble greeting-bubble">
          <div class="bubble-content">${answerHtml}</div>
        </div>
      </div>`;
    messageList.appendChild(div);
    scrollBottom();
    return;
  }

  // 1b. Write-attempt / safety block - show clean red-tinted banner, no badges
  if (data.intent === 'write_attempt' || data.result_type === 'safety_block') {
    div.innerHTML = `
      <div class="avatar">AI</div>
      <div class="msg-body">
        <div class="msg-name">Data Assistant</div>
        <div class="bubble" style="border-left: 3px solid var(--danger, #f87171);">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
            <span class="badge badge-readonly-sm">Read Only</span>
            <span style="font-size:11px;color:var(--danger,#f87171);font-weight:600;">Write Blocked</span>
          </div>
          <div class="bubble-content">${answerHtml}</div>
        </div>
      </div>`;
    messageList.appendChild(div);
    scrollBottom();
    return;
  }

  // 2. Unknown / no-match response check
  if (data.intent === 'unknown') {
    div.innerHTML = `
      <div class="avatar">AI</div>
      <div class="msg-body">
        <div class="msg-name">Data Assistant</div>
        <div class="bubble unknown-bubble">
          <div class="bubble-content">${answerHtml}</div>
          ${nextHtml}
        </div>
      </div>`;
    messageList.appendChild(div);
    scrollBottom();
    return;
  }

  // 3. Standard response with badges, confidence, and sources
  const sourcesHtml = renderSources(data.sources || []);
  const mcpTraceHtml = renderMcpTrace(data.mcp_trace || [], data.checked_sources || []);

  // Suppress inline record cards when the text answer already contains formatted
  // record details (business entity search, exact value search).
  // Cards are still available via CSV export through found_data.
  const intent = data.intent || '';
  const suppressCards = (
    intent.startsWith('business_entity_search:') ||
    intent === 'exact_value_search' ||
    (typeof data.answer === 'string' && data.answer.includes('Row ID:') && data.found_data && data.found_data.length > 0)
  );
  const cleanRecordsHtml = suppressCards ? '' : renderCleanRecords(data.found_data || []);
  
  // Calculate confidence labels and classes dynamically
  let confLabel = 'No Match';
  let confClass = 'badge-conf-none';
  const confScore = Number(data.confidence || 0);
  if (confScore >= 85) {
    confLabel = 'High';
    confClass = 'badge-conf-high';
  } else if (confScore >= 60) {
    confLabel = 'Medium';
    confClass = 'badge-conf-medium';
  } else if (confScore >= 1) {
    confLabel = 'Low';
    confClass = 'badge-conf-low';
  } else {
    confLabel = 'No Match';
    confClass = 'badge-conf-none';
  }

  const readOnlyTag = `<span class="badge badge-readonly-sm">Read Only</span>`;
  const confTag = `<span class="badge ${confClass}">Match ${confLabel}</span>`;
  const sourceBackedTag = (
    (data.sources && data.sources.length > 0) ||
    (data.checked_sources && data.checked_sources.length > 0)
  )
    ? `<span class="badge badge-source-backed">Source-backed</span>`
    : '';

  const badgesHtml = `<div class="assistant-badges">${readOnlyTag}${confTag}${sourceBackedTag}</div>`;

  const msgId = 'msg-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
  div.id = msgId;
  div.dataset.raw = JSON.stringify(data);
  
  // Check if we have matching records to show CSV button
  const hasTable = data.found_data && data.found_data.length > 0;
  
  const exportBtnHtml = `
    <div class="msg-export-actions" style="margin-top: 12px; display: flex; gap: 8px; border-top: 1px solid var(--border); padding-top: 8px;">
      <button class="export-btn icon-btn" style="width: auto; height: auto; padding: 4px 8px; font-size: 11px; display: flex; align-items: center; gap: 4px;" onclick="copyMessageText(this)" title="Copy answer text">Copy</button>
      <button class="export-btn icon-btn" style="width: auto; height: auto; padding: 4px 8px; font-size: 11px; display: flex; align-items: center; gap: 4px;" onclick="exportMessageJson(this)" title="Export JSON response">JSON</button>
      ${hasTable ? `<button class="export-btn icon-btn" style="width: auto; height: auto; padding: 4px 8px; font-size: 11px; display: flex; align-items: center; gap: 4px;" onclick="exportMessageCsv(this)" title="Export CSV data">CSV</button>` : ''}
    </div>
  `;

  div.innerHTML = `
    <div class="avatar">AI</div>
    <div class="msg-body">
      <div class="msg-name">Data Assistant</div>
      <div class="bubble">
        ${badgesHtml}
        <div class="bubble-content">${answerHtml}</div>
        ${cleanRecordsHtml}
        ${sourcesHtml}
        ${mcpTraceHtml}
        ${nextHtml}
        ${exportBtnHtml}
      </div>
    </div>`;
  messageList.appendChild(div);
  scrollBottom();
}

function renderMcpTrace(trace, checkedSources) {
  const hasTrace = Array.isArray(trace) && trace.length > 0;
  const hasSources = Array.isArray(checkedSources) && checkedSources.length > 0;
  if (!hasTrace && !hasSources) return '';

  const traceRows = hasTrace ? trace.slice(0, 8).map(t => {
    const transport = t.transport || 'unknown';
    const tool = t.tool || 'unknown_tool';
    const count = t.records_returned ?? 0;
    const server = t.server_url || '';
    const fallback = t.fallback_reason ? `<div class="mcp-trace-note">Fallback: ${escHtml(t.fallback_reason)}</div>` : '';
    return `
      <div class="mcp-trace-row">
        <span class="mcp-tool">${escHtml(tool)}</span>
        <span>${escHtml(transport)}</span>
        <span>${escHtml(count)} rows</span>
        ${server ? `<span>${escHtml(server)}</span>` : ''}
        ${fallback}
      </div>`;
  }).join('') : '<div class="mcp-empty">No MCP tool trace returned.</div>';

  const sourceRows = hasSources ? checkedSources.slice(0, 12).map(s => (
    `<span class="mcp-source-pill">${escHtml(s)}</span>`
  )).join('') : '';

  return `
    <details class="mcp-trace-details">
      <summary>MCP trace and checked sources</summary>
      <div class="mcp-trace-list">${traceRows}</div>
      ${sourceRows ? `<div class="mcp-source-list">${sourceRows}</div>` : ''}
    </details>`;
}

function renderCleanRecords(foundData) {
  if (!foundData || foundData.length === 0) return '';
  
  // Only display top 5 records by default
  const topRecords = foundData.slice(0, 5);

  const entityIcon = (item) => {
    const t = ((item.table || item._table || '') + '').toLowerCase();
    if (t.includes('invoice')) return '\ud83e\uddfe';
    if (t.includes('customer')) return '\ud83e\uddd1\u200d\ud83d\udcbc';
    if (t.includes('supplier')) return '\ud83d\ude9a';
    if (t.includes('product') || t.includes('item')) return '\ud83d\udce6';
    return '\ud83d\uddc2\ufe0f';
  };
  
  const cardsHtml = topRecords.map(item => {
    const icon = entityIcon(item);
    const title = item.display_title || item.invoice_number || item.customer_name || item.supplier_name || item.product_name || 'Database Record';
    const subtitle = item.display_subtitle || '';
    const summary = item.display_summary || '';
    
    // Build important fields html
    const importantFields = item.important_fields || {};
    let fieldsHtml = '';
    const fieldsKeys = Object.keys(importantFields);
    if (fieldsKeys.length > 0) {
      const fieldsList = fieldsKeys.map(k => {
        const val = importantFields[k];
        if (val === undefined || val === null || val === '') return '';
        const label = k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        let valStr = String(val);
        if (valStr.length > 60) {
          valStr = valStr.substring(0, 57) + '...';
        }
        return `
          <div class="db-record-field">
            <span class="db-record-field-label">${escHtml(label)}:</span>
            <span class="db-record-field-value">${escHtml(valStr)}</span>
          </div>`;
      }).join('');
      fieldsHtml = `<div class="db-record-fields">${fieldsList}</div>`;
    }
    
    // Hide raw_row inside collapsible details
    const rawRow = item.raw_row || item.row_preview || item;
    const rawRowCleaned = { ...rawRow };
    delete rawRowCleaned.display_title;
    delete rawRowCleaned.display_subtitle;
    delete rawRowCleaned.display_summary;
    delete rawRowCleaned.important_fields;
    delete rawRowCleaned.raw_row;
    delete rawRowCleaned.row_preview;
    
    const collapsibleHtml = `
      <details class="raw-row-details">
        <summary>View full row data</summary>
        <pre><code>${escHtml(JSON.stringify(rawRowCleaned, null, 2))}</code></pre>
      </details>
    `;
    
    return `
      <div class="db-record-card">
        <div class="db-record-header">
          <span class="db-record-icon">${icon}</span>
          <span class="db-record-title">${escHtml(title)}</span>
          ${subtitle ? `<span class="db-record-subtitle">${escHtml(subtitle)}</span>` : ''}
        </div>
        ${summary ? `<div class="db-record-summary">${escHtml(summary)}</div>` : ''}
        ${fieldsHtml}
        ${collapsibleHtml}
      </div>`;
  }).join('');
  
  return `<div class="db-records-container">${cardsHtml}</div>`;
}

function appendErrorMessage(text) {
  const div = document.createElement('div');
  div.className = 'msg-assistant fade-in';
  div.innerHTML = `
    <div class="avatar">AI</div>
    <div class="msg-body">
      <div class="msg-name">Data Assistant</div>
      <div class="bubble">
        <div class="error-banner">Warning ${escHtml(text)}</div>
        <div style="margin-top:10px;font-size:12px;color:var(--text-muted)">
          Make sure the backend is running:<br/>
          <code style="font-size:11px">uvicorn app.main:app --host 127.0.0.1 --port 8200</code>
        </div>
      </div>
    </div>`;
  messageList.appendChild(div);
  scrollBottom();
}

// --- Renderers ----------------------------------------------------------------
function renderMarkdown(text) {
  // Very lightweight markdown renderer
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n  -\s?/g, '</li><li>')
    .replace(/^  -\s?/gm, '<li>')
    .replace(/(<li>[\s\S]*?)<\/li>/g, '<ul>$1</li></ul>')
    .replace(/\n/g, '<br/>');
}

function renderSources(sources) {
  if (!sources || sources.length === 0) return '';

  const groups = {};
  sources.forEach(s => {
    let type = s.type || 'Database Table';
    let name = s.name || '';
    if (!name) {
      if (type === 'Validation Result') name = 'validation_results';
      else if (type === 'OCR Result') name = 'ocr_results';
      else name = 'training_mappings';
    }
    const key = `${type}||${name}`;
    if (!groups[key]) {
      groups[key] = {
        type: type,
        name: name,
        records: []
      };
    }
    groups[key].records.push(s);
  });

  const cards = Object.values(groups).map(g => {
    const type = g.type;
    const name = g.name;
    const count = g.records.length;
    const tag = type === 'Dataset' ? 'json' : type === 'Database Table' ? 'table' : 'record';
    
    // Collect unique non-empty record IDs
    const recordIds = g.records
      .map(r => r.record_id)
      .filter(id => id !== undefined && id !== null && id !== '');
    const uniqueIds = Array.from(new Set(recordIds));
    const idsStr = uniqueIds.length > 0 ? (uniqueIds.length === 1 ? `ID: ${uniqueIds[0]}` : `IDs: ${uniqueIds.join(', ')}`) : '';
    
    // Get average confidence
    const confs = g.records.map(r => r.confidence).filter(c => c != null);
    let confStr = '';
    if (confs.length > 0) {
      const avgConf = confs.reduce((a, b) => a + b, 0) / confs.length;
      const pct = avgConf > 1 ? Math.round(avgConf) : Math.round(avgConf * 100);
      confStr = `Match: ${pct}%`;
    }
    
    const countStr = count === 1 ? '1 record found' : `${count} records found`;

    return `
      <div class="source-card slide-in">
        <div class="sc-type">${escHtml(type)}</div>
        <div class="sc-name">${escHtml(name)}</div>
        <div style="font-size:11px;color:var(--text-secondary);margin-top:4px;">${escHtml(countStr)}</div>
        ${idsStr ? `<div style="font-size:10px;color:var(--text-muted);margin-top:2px;">${escHtml(idsStr)}</div>` : ''}
        <div style="display:flex;align-items:center;margin-top:6px;gap:6px;flex-wrap:wrap;">
          ${confStr ? `<span class="sc-tag ${tag}">${escHtml(confStr)}</span>` : ''}
          <span class="sc-tag table">Read Only</span>
        </div>
      </div>`;
  }).join('');

  return `
    <details class="source-section-details" style="margin-top: 14px; border-top: 1px solid var(--border); padding-top: 10px;">
      <summary style="font-size: 11.5px; font-weight: 600; color: var(--text-muted); cursor: pointer; user-select: none; list-style: none;">
        Checked Sources (${sources.length}) <span style="font-size:9px;color:var(--accent)">v</span>
      </summary>
      <div class="source-cards" style="margin-top: 8px;">
        ${cards}
      </div>
    </details>`;
}

function renderConfidence(conf, label) {
  if (conf === undefined || conf === null) return '';
  const pct = conf > 1 ? Math.round(conf) : Math.round(conf * 100);
  const cls = label === 'High' ? 'conf-high' : label === 'Medium' ? 'conf-medium' : label === 'Low' ? 'conf-low' : '';
  return `
    <div class="confidence-row ${cls}">
      <span>Confidence Score:</span>
      <div class="conf-bar">
        <div class="conf-bar-fill" style="width:${pct}%"></div>
      </div>
      <span class="conf-label">${pct}% (${label || '-'})</span>
    </div>`;
}

// --- Utils --------------------------------------------------------------------
function escHtml(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function highlightJson(jsonObj) {
  if (typeof jsonObj !== 'string') {
    jsonObj = JSON.stringify(jsonObj, null, 2);
  }
  return jsonObj.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, function (match) {
    let cls = 'json-number';
    if (/^"/.test(match)) {
      if (/:$/.test(match)) {
        cls = 'json-key';
      } else {
        cls = 'json-string';
      }
    } else if (/true|false/.test(match)) {
      cls = 'json-boolean';
    } else if (/null/.test(match)) {
      cls = 'json-null';
    }
    return '<span class="' + cls + '">' + match + '</span>';
  });
}

function scrollBottom() {
  requestAnimationFrame(() => {
    messageList.scrollTop = messageList.scrollHeight;
  });
}

function removeElement(id) {
  const el = $(id);
  if (el) el.remove();
}

// --- Export Window Actions ---------------------------------------------------
window.copyMessageText = (btn) => {
  const bubble = btn.closest('.bubble');
  const content = bubble.querySelector('.bubble-content').innerText;
  navigator.clipboard.writeText(content);
  btn.textContent = 'Copied';
  setTimeout(() => btn.textContent = 'Copy', 2000);
};

window.exportMessageJson = (btn) => {
  const msgDiv = btn.closest('.msg-assistant');
  const rawData = JSON.parse(msgDiv.dataset.raw);
  
  const blob = new Blob([JSON.stringify(rawData, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `chat_result_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
};

window.exportMessageCsv = (btn) => {
  const msgDiv = btn.closest('.msg-assistant');
  const rawData = JSON.parse(msgDiv.dataset.raw);
  
  let records = [];
  if (rawData.found_data && rawData.found_data.length > 0) {
    records = rawData.found_data;
  }
  
  if (records.length === 0) {
    alert('No tabular data found to export as CSV.');
    return;
  }
  
  const flatRecords = records.map(r => {
    if (r.record && typeof r.record === 'object') {
      return { dataset: r.dataset, ...r.record };
    }
    return r;
  });
  
  const keys = Array.from(new Set(flatRecords.flatMap(r => Object.keys(r))));
  const csvRows = [];
  csvRows.push(keys.join(','));
  
  for (const row of flatRecords) {
    const values = keys.map(k => {
      const val = row[k];
      const valStr = typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val ?? '');
      return `"${valStr.replace(/"/g, '""')}"`;
    });
    csvRows.push(values.join(','));
  }
  
  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `chat_result_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
};

async function performManualDbSearch() {
  const input = $('manual-db-search-input');
  const resultsDiv = $('manual-db-search-results');
  if (!input || !resultsDiv) return;

  const query = input.value.trim();
  if (!query) {
    resultsDiv.style.display = 'none';
    return;
  }

  resultsDiv.style.display = 'block';
  resultsDiv.innerHTML = `
    <div style="padding: 20px; text-align: center; color: var(--text-muted);">
      Searching...
    </div>
  `;

  try {
    const res = await fetch(`${API}/api/db/search?q=${encodeURIComponent(query)}&limit=20`);
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || 'Search query failed');
    }
    const data = await res.json();
    
    // Render the structured results
    let html = '';
    
    // 1. If it's a safety block or greeting or no match
    if (data.intent === 'write_attempt' || data.result_type === 'safety_block') {
      html = `
        <div class="error-banner" style="margin-bottom: 12px; font-weight: 500;">
          Warning ${escHtml(data.answer)}
        </div>
      `;
    } else if (data.result_type === 'greeting') {
      html = `
        <div style="padding: 12px; background: var(--accent-dim); border-radius: var(--radius-sm); border: 1px solid var(--border-accent); color: var(--text-primary); line-height: 1.6;">
          Hi ${escHtml(data.answer)}
        </div>
      `;
    } else if (!data.primary_results || data.primary_results.length === 0) {
      // Show answer / no-match clearly
      html = `
        <div style="padding: 12px; background: var(--bg-card-hover); border-radius: var(--radius-sm); border: 1px solid var(--border); color: var(--text-secondary); line-height: 1.6;">
          ${data.answer ? escHtml(data.answer).replace(/\n/g, '<br/>') : 'No results found.'}
        </div>
      `;
    } else {
      // 2. Primary Results
      let cardsHtml = data.primary_results.map(r => {
        const title = r.display_title || r.name || 'Record';
        const subtitle = r.display_subtitle || '';
        const summary = r.display_summary || '';
        const tbl = r.table || r._table || 'unknown';
        const rowId = r.row_id || r.rowid || r.id || '?';
        
        let detailsHtml = '';
        if (r.important_fields) {
          detailsHtml = Object.entries(r.important_fields)
            .filter(([k, v]) => v !== null && v !== '')
            .map(([k, v]) => `<div><strong>${escHtml(k)}:</strong> ${escHtml(v)}</div>`)
            .join('');
        }
        
        return `
          <div style="background: var(--bg-card-hover); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px; margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
              <strong style="color: var(--accent-light); font-size: 14px;">${escHtml(title)}</strong>
              <span class="panel-badge" style="background: var(--accent-dim); color: var(--accent-light); font-size: 9.5px; padding: 1px 6px; border-radius: 4px;">${escHtml(tbl)} - Row ${escHtml(rowId)}</span>
            </div>
            <div style="font-size: 12.5px; color: var(--text-secondary); margin-bottom: 6px;">${escHtml(subtitle)}</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">${escHtml(summary)}</div>
            <div style="font-size: 11.5px; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 4px; padding-top: 6px; border-top: 1px dashed var(--border);">
              ${detailsHtml}
            </div>
          </div>
        `;
      }).join('');
      
      html = `
        <div style="margin-bottom: 16px;">
          <h3 style="font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-primary); margin-bottom: 8px;">Primary Results</h3>
          ${cardsHtml}
        </div>
      `;
    }
    
    // 3. Related Results
    if (data.related_results && data.related_results.length > 0) {
      let relatedCardsHtml = data.related_results.map(r => {
        const title = r.display_title || r.name || 'Related Match';
        const subtitle = r.display_subtitle || '';
        const tbl = r.table || r._table || 'unknown';
        const rowId = r.row_id || r.rowid || r.id || '?';
        
        return `
          <div style="background: var(--bg-card-hover); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 12px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
            <div>
              <strong style="color: var(--text-primary); font-size: 12.5px;">${escHtml(title)}</strong>
              <span style="font-size: 11.5px; color: var(--text-muted); margin-left: 8px;">${escHtml(subtitle)}</span>
            </div>
            <span class="panel-badge" style="font-size: 9.5px; padding: 1px 6px; border-radius: 4px;">${escHtml(tbl)} - Row ${escHtml(rowId)}</span>
          </div>
        `;
      }).join('');
      
      html += `
        <div style="margin-top: 16px; border-top: 1px solid var(--border); padding-top: 16px;">
          <h3 style="font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-primary); margin-bottom: 8px;">Related Records</h3>
          ${relatedCardsHtml}
        </div>
      `;
    }
    
    // Append answer text if it contains extra guidelines and if there are primary results to provide context
    if (data.answer && data.primary_results && data.primary_results.length > 0) {
      html += `
        <div style="margin-top: 12px; font-size: 12.5px; color: var(--text-secondary); line-height: 1.5; padding: 8px 12px; background: var(--bg-secondary); border-radius: var(--radius-sm);">
          ${escHtml(data.answer).replace(/\n/g, '<br/>')}
        </div>
      `;
    }

    resultsDiv.innerHTML = html;
  } catch (err) {
    console.error('Manual search error:', err);
    resultsDiv.innerHTML = `
      <div class="error-banner">
        Warning Failed to perform search: ${escHtml(err.message)}
      </div>
    `;
  }
}
