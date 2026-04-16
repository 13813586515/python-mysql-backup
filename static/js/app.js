const API_BASE = '';

const state = {
    config: {},
    databases: [],
    logs: [],
    eventSource: null,
    statusInterval: null
};

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    loadConfig();
    initEventListeners();
    connectLogStream();
    startStatusPolling();
    loadBackupHistory();
});

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => container.removeChild(toast), 300);
    }, 3000);
}

function initTabs() {
    const navBtns = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;

            navBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(t => t.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(`${tabId}-tab`).classList.add('active');
        });
    });
}

async function fetchApi(endpoint, options = {}) {
    try {
        const url = `${API_BASE}${endpoint}`;
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        return { success: false, message: '网络错误' };
    }
}

async function loadConfig() {
    const result = await fetchApi('/api/config', { method: 'GET' });
    if (result.success) {
        state.config = result.config;
        populateConfigForm(result.config);
        populateStrategyForm(result.config);
    }
}

function populateConfigForm(config) {
    const form = document.getElementById('config-form');
    if (form.db_host) form.db_host.value = config.db_host || 'localhost';
    if (form.db_port) form.db_port.value = config.db_port || 3306;
    if (form.db_user) form.db_user.value = config.db_user || 'root';
    if (form.db_password) form.db_password.value = config.db_password || '';
    if (form.db_name) form.db_name.value = config.db_name || '';
    
    if (config.selected_databases && config.selected_databases.length > 0) {
        state.config.selected_databases = config.selected_databases;
    }
}

function populateStrategyForm(config) {
    const form = document.getElementById('strategy-form');
    if (form.backup_path) form.backup_path.value = config.backup_path || './backups';
    if (form.retention_days) form.retention_days.value = config.retention_days || 30;
    if (form.backup_mode) form.backup_mode.value = config.backup_mode || 'manual';
    if (form.schedule_type) form.schedule_type.value = config.schedule_type || 'daily';
    if (form.schedule_time) form.schedule_time.value = config.schedule_time || '02:00';
    if (form.schedule_days) form.schedule_days.value = config.schedule_days || 7;

    updateScheduleVisibility();
}

function updateScheduleVisibility() {
    const backupMode = document.getElementById('backup_mode').value;
    const scheduleType = document.getElementById('schedule_type').value;
    
    const scheduleTypeGroup = document.getElementById('schedule-type-group');
    const scheduleTimeGroup = document.getElementById('schedule-time-group');
    const scheduleDaysGroup = document.getElementById('schedule-days-group');

    if (backupMode === 'scheduled') {
        scheduleTypeGroup.style.display = 'block';
        scheduleTimeGroup.style.display = 'block';
        
        if (scheduleType === 'interval') {
            scheduleDaysGroup.style.display = 'block';
        } else {
            scheduleDaysGroup.style.display = 'none';
        }
    } else {
        scheduleTypeGroup.style.display = 'none';
        scheduleTimeGroup.style.display = 'none';
        scheduleDaysGroup.style.display = 'none';
    }
}

function initEventListeners() {
    document.getElementById('backup_mode').addEventListener('change', updateScheduleVisibility);
    document.getElementById('schedule_type').addEventListener('change', updateScheduleVisibility);

    document.getElementById('test-connection-btn').addEventListener('click', testConnection);
    document.getElementById('save-config-btn').addEventListener('click', saveConfig);
    document.getElementById('save-strategy-btn').addEventListener('click', saveStrategy);
    document.getElementById('start-backup-btn').addEventListener('click', startBackup);
    document.getElementById('refresh-status-btn').addEventListener('click', refreshStatus);
    document.getElementById('clear-logs-btn').addEventListener('click', clearLogs);
    document.getElementById('refresh-history-btn').addEventListener('click', loadBackupHistory);
}

function setButtonLoading(btnId, loading) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    
    const textSpan = btn.querySelector('.btn-text');
    const loaderSpan = btn.querySelector('.btn-loader');
    
    if (textSpan) textSpan.style.display = loading ? 'none' : 'inline';
    if (loaderSpan) loaderSpan.style.display = loading ? 'inline' : 'none';
    btn.disabled = loading;
}

async function testConnection() {
    const form = document.getElementById('config-form');
    const config = {
        db_host: form.db_host.value || 'localhost',
        db_port: parseInt(form.db_port.value) || 3306,
        db_user: form.db_user.value || 'root',
        db_password: form.db_password.value,
        db_name: form.db_name.value || ''
    };

    setButtonLoading('test-connection-btn', true);

    const result = await fetchApi('/api/config/test', {
        method: 'POST',
        body: JSON.stringify(config)
    });

    setButtonLoading('test-connection-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
        await loadDatabases(config);
    } else {
        showToast(result.message, 'error');
    }
}

async function loadDatabases(config) {
    const result = await fetchApi('/api/databases', {
        method: 'POST',
        body: JSON.stringify(config)
    });

    if (result.success && result.databases.length > 0) {
        state.databases = result.databases;
        displayDatabaseList(result.databases);
    } else {
        showToast('无法加载数据库列表', 'warning');
    }
}

function displayDatabaseList(databases) {
    const container = document.getElementById('database-list');
    const selector = document.querySelector('.database-selector');
    
    if (databases.length === 0) {
        container.innerHTML = '<p class="hint">没有找到可用的数据库</p>';
        selector.style.display = 'none';
        return;
    }

    selector.style.display = 'block';
    const selectedDbs = state.config.selected_databases || [];

    container.innerHTML = databases.map(db => `
        <div class="checkbox-item">
            <input type="checkbox" id="db-${db}" name="selected_databases" value="${db}" 
                ${selectedDbs.includes(db) ? 'checked' : ''}>
            <label for="db-${db}">${db}</label>
        </div>
    `).join('');
}

async function saveConfig() {
    const form = document.getElementById('config-form');
    const selectedDbs = Array.from(
        document.querySelectorAll('input[name="selected_databases"]:checked')
    ).map(cb => cb.value);

    const config = {
        ...state.config,
        db_host: form.db_host.value || 'localhost',
        db_port: parseInt(form.db_port.value) || 3306,
        db_user: form.db_user.value || 'root',
        db_password: form.db_password.value,
        db_name: form.db_name.value || '',
        selected_databases: selectedDbs
    };

    setButtonLoading('save-config-btn', true);

    const result = await fetchApi('/api/config', {
        method: 'POST',
        body: JSON.stringify(config)
    });

    setButtonLoading('save-config-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
        state.config = config;
    } else {
        showToast(result.message, 'error');
    }
}

async function saveStrategy() {
    const form = document.getElementById('strategy-form');
    
    const config = {
        ...state.config,
        backup_path: form.backup_path.value || './backups',
        retention_days: parseInt(form.retention_days.value) || 30,
        backup_mode: form.backup_mode.value || 'manual',
        schedule_type: form.schedule_type.value || 'daily',
        schedule_time: form.schedule_time.value || '02:00',
        schedule_days: parseInt(form.schedule_days.value) || 7
    };

    setButtonLoading('save-strategy-btn', true);

    const result = await fetchApi('/api/config', {
        method: 'POST',
        body: JSON.stringify(config)
    });

    setButtonLoading('save-strategy-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
        state.config = config;
        await refreshStatus();
    } else {
        showToast(result.message, 'error');
    }
}

async function startBackup() {
    const startBtn = document.getElementById('start-backup-btn');
    const progressContainer = document.getElementById('progress-container');
    
    startBtn.style.display = 'none';
    progressContainer.style.display = 'block';
    
    setButtonLoading('start-backup-btn', true);

    const result = await fetchApi('/api/backup/start', {
        method: 'POST'
    });

    setButtonLoading('start-backup-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
    } else {
        showToast(result.message, 'error');
        startBtn.style.display = 'inline-block';
        progressContainer.style.display = 'none';
    }
}

function updateTaskStatus(status) {
    const statusEl = document.getElementById('task-status');
    const startBtn = document.getElementById('start-backup-btn');
    const progressContainer = document.getElementById('progress-container');
    const progressFill = document.getElementById('progress-fill');
    const progressMessage = document.getElementById('progress-message');
    const progressPercent = document.getElementById('progress-percent');

    const statusInfo = {
        'idle': { class: 'status-idle', text: '空闲' },
        'running': { class: 'status-running', text: '运行中' },
        'completed': { class: 'status-completed', text: '已完成' },
        'error': { class: 'status-error', text: '错误' }
    };

    const info = statusInfo[status.progress.status] || statusInfo['idle'];
    
    statusEl.innerHTML = `
        <span class="status-dot ${info.class}"></span>
        <span class="status-text">${info.text}</span>
    `;

    if (status.running || status.progress.status === 'running') {
        startBtn.style.display = 'none';
        progressContainer.style.display = 'block';
        
        const current = status.progress.progress || 0;
        const total = status.progress.total || 0;
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        
        progressFill.style.width = `${percent}%`;
        progressMessage.textContent = status.progress.message || '执行中...';
        progressPercent.textContent = `${percent}%`;
    } else {
        startBtn.style.display = 'inline-block';
        
        if (status.progress.status === 'completed') {
            progressFill.style.width = '100%';
            progressMessage.textContent = status.progress.message || '备份完成';
            progressPercent.textContent = '100%';
        } else if (status.progress.status === 'error') {
            progressMessage.textContent = status.progress.message || '备份失败';
        }
    }
}

function updateSchedulerStatus(status) {
    const schedulerEl = document.getElementById('scheduler-status');
    const nextRunItem = document.getElementById('next-run-item');
    const nextRunEl = document.getElementById('next-run-time');

    if (status.scheduler_running) {
        schedulerEl.innerHTML = `
            <span class="status-dot status-running"></span>
            <span class="status-text">运行中</span>
        `;
    } else {
        schedulerEl.innerHTML = `
            <span class="status-dot status-idle"></span>
            <span class="status-text">未运行</span>
        `;
    }

    if (status.job_info && status.job_info.next_run_time) {
        nextRunItem.style.display = 'flex';
        nextRunEl.textContent = status.job_info.next_run_time;
    } else {
        nextRunItem.style.display = 'none';
    }
}

async function refreshStatus() {
    const backupStatus = await fetchApi('/api/backup/status', { method: 'GET' });
    if (backupStatus.success) {
        updateTaskStatus(backupStatus);
    }

    const schedulerStatus = await fetchApi('/api/scheduler/status', { method: 'GET' });
    if (schedulerStatus.success) {
        updateSchedulerStatus(schedulerStatus);
    }
}

function startStatusPolling() {
    refreshStatus();
    state.statusInterval = setInterval(refreshStatus, 2000);
}

function connectLogStream() {
    if (state.eventSource) {
        state.eventSource.close();
    }

    state.eventSource = new EventSource(`${API_BASE}/api/logs/stream`);

    state.eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.timestamp) {
                addLogEntry(data);
            }
        } catch (e) {
        }
    };

    state.eventSource.onerror = (error) => {
        console.error('EventSource error:', error);
        setTimeout(connectLogStream, 5000);
    };
}

function addLogEntry(log) {
    const consoleEl = document.getElementById('log-console');
    const defaultEntry = consoleEl.querySelector('.log-entry:first-child');
    if (defaultEntry && defaultEntry.textContent.includes('等待日志消息')) {
        defaultEntry.remove();
    }

    const entry = document.createElement('div');
    entry.className = `log-entry log-${log.level.toLowerCase()}`;
    
    const levelColor = {
        'INFO': 'info',
        'WARNING': 'warning',
        'ERROR': 'error'
    };
    const levelClass = levelColor[log.level] || 'info';

    entry.innerHTML = `
        <span class="log-time">${log.timestamp}</span>
        <span class="log-level ${levelClass}">[${log.level}]</span>
        <span class="log-message">${escapeHtml(log.message)}</span>
    `;

    consoleEl.appendChild(entry);
    consoleEl.scrollTop = consoleEl.scrollHeight;

    state.logs.push(log);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function clearLogs() {
    const consoleEl = document.getElementById('log-console');
    consoleEl.innerHTML = `
        <div class="log-entry log-info">
            <span class="log-time">--</span>
            <span class="log-level">[INFO]</span>
            <span class="log-message">等待日志消息...</span>
        </div>
    `;
    state.logs = [];
    showToast('日志已清空', 'success');
}

async function loadBackupHistory() {
    const result = await fetchApi('/api/backups', { method: 'GET' });
    const tbody = document.querySelector('#backup-table tbody');

    if (!result.success || !result.files || result.files.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="text-center">暂无备份记录</td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = result.files.map(file => `
        <tr>
            <td>${escapeHtml(file.filename)}</td>
            <td>${file.created_time}</td>
            <td>${file.size_mb} MB</td>
            <td>
                <button class="btn btn-sm btn-secondary" onclick="downloadBackup('${escapeHtml(file.filename)}')">
                    下载
                </button>
            </td>
        </tr>
    `).join('');
}

function downloadBackup(filename) {
    window.location.href = `${API_BASE}/api/backups/download?filename=${encodeURIComponent(filename)}`;
}
