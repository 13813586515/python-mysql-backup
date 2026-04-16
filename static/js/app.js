const API_BASE = '';

const state = {
    configs: [],
    currentConfigId: null,
    globalConfig: {},
    logs: [],
    eventSource: null,
    statusInterval: null,
    editingConfigId: null,
    loadedDatabases: []
};

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    loadAllConfigs();
    loadGlobalConfig();
    initEventListeners();
    connectLogStream();
    startStatusPolling();
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

function setButtonLoading(btnId, loading) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    
    const textSpan = btn.querySelector('.btn-text');
    const loaderSpan = btn.querySelector('.btn-loader');
    
    if (textSpan) textSpan.style.display = loading ? 'none' : 'inline';
    if (loaderSpan) loaderSpan.style.display = loading ? 'inline' : 'none';
    btn.disabled = loading;
}

function initTabs() {
    const navBtns = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    navBtns.forEach(btn => {
        btn.addEventListener('click', async () => {
            const tabId = btn.dataset.tab;

            navBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(t => t.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(`${tabId}-tab`).classList.add('active');

            if (tabId === 'config') {
                await loadAllConfigs();
            }
            if (tabId === 'strategy') {
                await loadGlobalConfig();
            }
            if (tabId === 'console') {
                await loadAllConfigs();
                updateCurrentConfigDisplay();
            }
            if (tabId === 'history') {
                await loadBackupHistory();
            }
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

async function loadAllConfigs() {
    const result = await fetchApi('/api/configs', { method: 'GET' });
    if (result.success) {
        state.configs = result.configs.database_configs || [];
        state.currentConfigId = result.configs.current_config_id;
        state.globalConfig = result.configs.global_config || {};
        renderConfigList();
        updateConfigSelector();
        updateCurrentConfigDisplay();
    }
}

function renderConfigList() {
    const container = document.getElementById('config-list-container');
    
    if (state.configs.length === 0) {
        container.innerHTML = `
            <div class="config-empty-state">
                <p>暂无数据库配置</p>
                <p>点击上方 "新增配置" 按钮添加第一个数据库配置</p>
            </div>
        `;
        return;
    }

    container.innerHTML = state.configs.map(config => {
        const isCurrent = config.id === state.currentConfigId;
        const selectedDbs = config.selected_databases || [];
        
        return `
            <div class="config-item ${isCurrent ? 'current' : ''}" data-config-id="${config.id}">
                <div class="config-header">
                    <div class="config-name">
                        ${escapeHtml(config.name)}
                        ${isCurrent ? '<span class="config-current-badge">当前使用</span>' : ''}
                    </div>
                </div>
                <div class="config-info">
                    <div class="config-info-item">
                        <strong>主机：</strong>${escapeHtml(config.db_host)}:${config.db_port}
                    </div>
                    <div class="config-info-item">
                        <strong>用户名：</strong>${escapeHtml(config.db_user)}
                    </div>
                </div>
                <div class="config-selected-dbs">
                    <strong>已选择的数据库：</strong>
                    <span class="config-selected-dbs-list">
                        ${selectedDbs.length > 0 
                            ? escapeHtml(selectedDbs.join(', ')) 
                            : '<span class="text-muted">未选择任何数据库（将备份所有）</span>'}
                    </span>
                </div>
                <div class="config-actions">
                    <button type="button" class="btn btn-primary btn-sm" onclick="selectConfig('${config.id}')" ${isCurrent ? 'disabled' : ''}>
                        设为当前
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="editConfig('${config.id}')">
                        编辑
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="testConfigConnection('${config.id}')">
                        测试连接
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="backupConfig('${config.id}')">
                        立即备份
                    </button>
                    <button type="button" class="btn btn-danger btn-sm" onclick="deleteConfig('${config.id}')">
                        删除
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function updateConfigSelector() {
    const selector = document.getElementById('config-selector');
    if (!selector) return;

    selector.innerHTML = '<option value="">-- 选择配置 --</option>' +
        state.configs.map(config => 
            `<option value="${config.id}" ${config.id === state.currentConfigId ? 'selected' : ''}>
                ${escapeHtml(config.name)} (${config.db_host}:${config.db_port})
            </option>`
        ).join('');
}

function updateCurrentConfigDisplay() {
    const infoEl = document.getElementById('current-config-info');
    const selector = document.getElementById('config-selector');
    const startBtn = document.getElementById('start-backup-btn');
    
    if (!infoEl) return;

    if (state.currentConfigId) {
        const currentConfig = state.configs.find(c => c.id === state.currentConfigId);
        if (currentConfig) {
            const selectedDbs = currentConfig.selected_databases || [];
            infoEl.innerHTML = `
                <div style="margin-bottom: 5px;">
                    <strong>${escapeHtml(currentConfig.name)}</strong> 
                    (${escapeHtml(currentConfig.db_host)}:${currentConfig.db_port})
                </div>
                <div style="font-size: 12px;">
                    已选择数据库：${selectedDbs.length > 0 
                        ? escapeHtml(selectedDbs.join(', ')) 
                        : '<span class="text-muted">所有数据库</span>'}
                </div>
            `;
            if (startBtn) startBtn.style.display = 'inline-block';
        } else {
            infoEl.innerHTML = '配置不存在，请重新选择';
            if (startBtn) startBtn.style.display = 'none';
        }
    } else {
        infoEl.innerHTML = '请先在"数据库配置"页面添加并选择一个配置';
        if (startBtn) startBtn.style.display = 'none';
    }
}

async function selectConfig(configId) {
    const result = await fetchApi(`/api/configs/${configId}/select`, {
        method: 'POST'
    });
    
    if (result.success) {
        state.currentConfigId = configId;
        showToast(result.message, 'success');
        await loadAllConfigs();
    } else {
        showToast(result.message, 'error');
    }
}

async function testConfigConnection(configId) {
    showToast('正在测试连接...', 'info');
    
    const result = await fetchApi(`/api/configs/${configId}/test`, {
        method: 'POST'
    });
    
    if (result.success) {
        showToast(result.message, 'success');
    } else {
        showToast(result.message, 'error');
    }
}

async function backupConfig(configId) {
    const config = state.configs.find(c => c.id === configId);
    if (!config) {
        showToast('配置不存在', 'error');
        return;
    }
    
    const selectedDbs = config.selected_databases || [];
    const dbCount = selectedDbs.length > 0 ? selectedDbs.length : '所有';
    
    if (!confirm(`确定要立即备份配置 "${config.name}" 吗？\n\n将备份：${dbCount} 个数据库`)) {
        return;
    }
    
    const result = await fetchApi('/api/backup/start', {
        method: 'POST',
        body: JSON.stringify({ config_id: configId })
    });
    
    if (result.success) {
        showToast(result.message, 'success');
    } else {
        showToast(result.message, 'error');
    }
}

async function deleteConfig(configId) {
    const config = state.configs.find(c => c.id === configId);
    if (!config) return;
    
    if (!confirm(`确定要删除配置 "${config.name}" 吗？此操作不可恢复。`)) {
        return;
    }
    
    const result = await fetchApi(`/api/configs/${configId}`, {
        method: 'DELETE'
    });
    
    if (result.success) {
        showToast(result.message, 'success');
        await loadAllConfigs();
    } else {
        showToast(result.message, 'error');
    }
}

function editConfig(configId) {
    const config = state.configs.find(c => c.id === configId);
    if (!config) {
        showToast('配置不存在', 'error');
        return;
    }
    
    state.editingConfigId = configId;
    state.loadedDatabases = [];
    
    document.getElementById('modal-title').textContent = '编辑数据库配置';
    
    const form = document.getElementById('config-form');
    form.config_name.value = config.name || '';
    form.config_db_host.value = config.db_host || 'localhost';
    form.config_db_port.value = config.db_port || 3306;
    form.config_db_user.value = config.db_user || 'root';
    form.config_db_password.value = '********';
    
    const dbSelection = document.getElementById('config-database-selection');
    const dbList = document.getElementById('config-database-list');
    
    const selectedDbs = config.selected_databases || [];
    if (selectedDbs.length > 0) {
        dbSelection.style.display = 'block';
        dbList.innerHTML = `
            <div class="select-all-container">
                <input type="checkbox" id="config-select-all-dbs" onchange="toggleConfigSelectAll(this)">
                <label for="config-select-all-dbs">全选/取消全选</label>
            </div>
            <div class="checkbox-group" style="padding-top: 5px;">
                ${selectedDbs.map(db => `
                    <div class="checkbox-item">
                        <input type="checkbox" id="config-db-${db}" name="config_selected_databases" value="${db}" checked
                            onchange="updateConfigSelectAllStatus()">
                        <label for="config-db-${db}">${db}</label>
                    </div>
                `).join('')}
            </div>
            <p class="hint" style="margin-top: 10px; font-size: 12px;">
                提示：点击 "测试连接" 按钮可重新加载完整的数据库列表
            </p>
        `;
    } else {
        dbSelection.style.display = 'block';
        dbList.innerHTML = '<p class="hint">请点击 "测试连接" 按钮加载数据库列表</p>';
    }
    
    openModal();
}

function addConfig() {
    state.editingConfigId = null;
    state.loadedDatabases = [];
    
    document.getElementById('modal-title').textContent = '新增数据库配置';
    
    const form = document.getElementById('config-form');
    form.config_name.value = '';
    form.config_db_host.value = 'localhost';
    form.config_db_port.value = 3306;
    form.config_db_user.value = 'root';
    form.config_db_password.value = '';
    
    document.getElementById('config-database-selection').style.display = 'none';
    document.getElementById('config-database-list').innerHTML = '<p class="hint">请先测试连接以加载数据库列表</p>';
    
    openModal();
}

function openModal() {
    document.getElementById('config-form-modal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('config-form-modal').style.display = 'none';
    state.editingConfigId = null;
    state.loadedDatabases = [];
}

async function testCurrentConnection() {
    const form = document.getElementById('config-form');
    const config = {
        name: form.config_name.value || '临时配置',
        db_host: form.config_db_host.value || 'localhost',
        db_port: parseInt(form.config_db_port.value) || 3306,
        db_user: form.config_db_user.value || 'root',
        db_password: form.config_db_password.value === '********' 
            ? (state.editingConfigId 
                ? (state.configs.find(c => c.id === state.editingConfigId)?.db_password || '')
                : '')
            : form.config_db_password.value
    };

    if (config.db_password === '********') {
        config.db_password = '';
    }

    setButtonLoading('test-current-connection-btn', true);
    showToast('正在测试连接...', 'info');

    let testConfigId = state.editingConfigId;
    let result;
    
    if (testConfigId) {
        const updateResult = await fetchApi(`/api/configs/${testConfigId}`, {
            method: 'PUT',
            body: JSON.stringify(config)
        });
        
        if (updateResult.success) {
            result = await fetchApi(`/api/configs/${testConfigId}/test`, {
                method: 'POST'
            });
        } else {
            result = updateResult;
        }
    } else {
        const createResult = await fetchApi('/api/configs', {
            method: 'POST',
            body: JSON.stringify(config)
        });
        
        if (createResult.success) {
            testConfigId = createResult.config.id;
            state.editingConfigId = testConfigId;
            await loadAllConfigs();
            
            result = await fetchApi(`/api/configs/${testConfigId}/test`, {
                method: 'POST'
            });
        } else {
            result = createResult;
        }
    }

    setButtonLoading('test-current-connection-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
        
        if (testConfigId) {
            const dbResult = await fetchApi(`/api/configs/${testConfigId}/databases`, {
                method: 'POST'
            });
            
            if (dbResult.success && dbResult.databases.length > 0) {
                state.loadedDatabases = dbResult.databases;
                displayDatabaseListForConfig(dbResult.databases, testConfigId);
            }
        }
    } else {
        showToast(result.message, 'error');
    }
}

function displayDatabaseListForConfig(databases, configId) {
    const container = document.getElementById('config-database-list');
    const selector = document.getElementById('config-database-selection');
    
    selector.style.display = 'block';
    
    const currentConfig = state.configs.find(c => c.id === configId);
    const selectedDbs = currentConfig?.selected_databases || [];

    let selectAllHtml = `
        <div class="select-all-container">
            <input type="checkbox" id="config-select-all-dbs" onchange="toggleConfigSelectAll(this)">
            <label for="config-select-all-dbs">全选/取消全选</label>
        </div>
    `;

    let databasesHtml = databases.map(db => `
        <div class="checkbox-item">
            <input type="checkbox" id="config-db-${db}" name="config_selected_databases" value="${db}" 
                ${selectedDbs.includes(db) ? 'checked' : ''}
                onchange="updateConfigSelectAllStatus()">
            <label for="config-db-${db}">${db}</label>
        </div>
    `).join('');

    container.innerHTML = selectAllHtml + '<div class="checkbox-group" style="padding-top: 5px;">' + databasesHtml + '</div>';
    
    updateConfigSelectAllStatus();
}

function toggleConfigSelectAll(checkbox) {
    const checkboxes = document.querySelectorAll('input[name="config_selected_databases"]');
    checkboxes.forEach(cb => {
        cb.checked = checkbox.checked;
    });
}

function updateConfigSelectAllStatus() {
    const checkboxes = document.querySelectorAll('input[name="config_selected_databases"]');
    const selectAllCheckbox = document.getElementById('config-select-all-dbs');
    
    if (checkboxes.length === 0 || !selectAllCheckbox) return;
    
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);
    const someChecked = Array.from(checkboxes).some(cb => cb.checked);
    
    selectAllCheckbox.checked = allChecked;
    selectAllCheckbox.indeterminate = someChecked && !allChecked;
}

async function saveConfigModal() {
    const form = document.getElementById('config-form');
    const name = form.config_name.value.trim();
    
    if (!name) {
        showToast('请输入配置名称', 'warning');
        return;
    }

    const selectedDbs = Array.from(
        document.querySelectorAll('input[name="config_selected_databases"]:checked')
    ).map(cb => cb.value);

    const password = form.config_db_password.value === '********'
        ? (state.editingConfigId 
            ? (state.configs.find(c => c.id === state.editingConfigId)?.db_password || '')
            : '')
        : form.config_db_password.value;

    const config = {
        name: name,
        db_host: form.config_db_host.value || 'localhost',
        db_port: parseInt(form.config_db_port.value) || 3306,
        db_user: form.config_db_user.value || 'root',
        db_password: password,
        selected_databases: selectedDbs
    };

    setButtonLoading('save-config-modal-btn', true);

    let result;
    
    if (state.editingConfigId) {
        result = await fetchApi(`/api/configs/${state.editingConfigId}`, {
            method: 'PUT',
            body: JSON.stringify(config)
        });
    } else {
        result = await fetchApi('/api/configs', {
            method: 'POST',
            body: JSON.stringify(config)
        });
    }

    setButtonLoading('save-config-modal-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
        closeModal();
        await loadAllConfigs();
    } else {
        showToast(result.message, 'error');
    }
}

async function loadGlobalConfig() {
    const result = await fetchApi('/api/global-config', { method: 'GET' });
    if (result.success) {
        state.globalConfig = result.config;
        populateStrategyForm(result.config);
    }
}

function populateStrategyForm(config) {
    const form = document.getElementById('strategy-form');
    if (form.backup_path) form.backup_path.value = config.backup_path || './backups';
    if (form.retention_days) form.retention_days.value = config.retention_days ?? 30;
    if (form.backup_mode) form.backup_mode.value = config.backup_mode || 'manual';
    if (form.schedule_type) form.schedule_type.value = config.schedule_type || 'daily';
    if (form.schedule_time) form.schedule_time.value = config.schedule_time || '02:00';
    if (form.schedule_days) form.schedule_days.value = config.schedule_days ?? 7;

    updateScheduleVisibility();
}

function updateScheduleVisibility() {
    const backupMode = document.getElementById('backup_mode')?.value;
    const scheduleType = document.getElementById('schedule_type')?.value;
    
    const scheduleTypeGroup = document.getElementById('schedule-type-group');
    const scheduleTimeGroup = document.getElementById('schedule-time-group');
    const scheduleDaysGroup = document.getElementById('schedule-days-group');

    if (!scheduleTypeGroup) return;

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
    const backupModeEl = document.getElementById('backup_mode');
    const scheduleTypeEl = document.getElementById('schedule_type');
    
    if (backupModeEl) backupModeEl.addEventListener('change', updateScheduleVisibility);
    if (scheduleTypeEl) scheduleTypeEl.addEventListener('change', updateScheduleVisibility);

    document.getElementById('add-config-btn')?.addEventListener('click', addConfig);
    document.getElementById('close-modal-btn')?.addEventListener('click', closeModal);
    document.getElementById('cancel-modal-btn')?.addEventListener('click', closeModal);
    document.getElementById('test-current-connection-btn')?.addEventListener('click', testCurrentConnection);
    document.getElementById('save-config-modal-btn')?.addEventListener('click', saveConfigModal);

    document.getElementById('save-strategy-btn')?.addEventListener('click', saveStrategy);
    document.getElementById('start-backup-btn')?.addEventListener('click', startBackup);
    document.getElementById('refresh-status-btn')?.addEventListener('click', refreshStatus);
    document.getElementById('clear-logs-btn')?.addEventListener('click', clearLogs);
    document.getElementById('refresh-history-btn')?.addEventListener('click', loadBackupHistory);
    document.getElementById('manual-cleanup-btn')?.addEventListener('click', manualCleanup);
    
    const configSelector = document.getElementById('config-selector');
    if (configSelector) {
        configSelector.addEventListener('change', async (e) => {
            const configId = e.target.value;
            if (configId) {
                await selectConfig(configId);
            }
        });
    }

    document.getElementById('config-form-modal')?.addEventListener('click', (e) => {
        if (e.target.id === 'config-form-modal') {
            closeModal();
        }
    });
}

async function saveStrategy() {
    const form = document.getElementById('strategy-form');
    
    const config = {
        backup_path: form.backup_path.value || './backups',
        retention_days: parseInt(form.retention_days.value) ?? 30,
        backup_mode: form.backup_mode.value || 'manual',
        schedule_type: form.schedule_type.value || 'daily',
        schedule_time: form.schedule_time.value || '02:00',
        schedule_days: parseInt(form.schedule_days.value) ?? 7
    };

    setButtonLoading('save-strategy-btn', true);

    const result = await fetchApi('/api/global-config', {
        method: 'PUT',
        body: JSON.stringify(config)
    });

    setButtonLoading('save-strategy-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
        state.globalConfig = config;
    } else {
        showToast(result.message, 'error');
    }
}

async function manualCleanup() {
    const form = document.getElementById('strategy-form');
    const retentionDays = parseInt(form.retention_days.value) ?? 30;

    let message = `确定要清理 ${retentionDays} 天前的备份文件吗？`;
    if (retentionDays === 0) {
        message = '保留天数设置为 0，将清理所有备份文件！确定继续吗？';
    }

    if (!confirm(message)) {
        return;
    }

    setButtonLoading('manual-cleanup-btn', true);

    const result = await fetchApi('/api/backups/cleanup', {
        method: 'POST',
        body: JSON.stringify({ retention_days: retentionDays })
    });

    setButtonLoading('manual-cleanup-btn', false);

    if (result.success) {
        showToast(result.message, 'success');
        await loadBackupHistory();
    } else {
        showToast(result.message, 'error');
    }
}

async function startBackup() {
    if (!state.currentConfigId) {
        showToast('请先选择一个数据库配置', 'warning');
        return;
    }

    const currentConfig = state.configs.find(c => c.id === state.currentConfigId);
    if (!currentConfig) {
        showToast('配置不存在', 'error');
        return;
    }

    const selectedDbs = currentConfig.selected_databases || [];
    const dbCount = selectedDbs.length > 0 ? selectedDbs.length : '所有';
    
    if (!confirm(`确定要立即备份配置 "${currentConfig.name}" 吗？\n\n将备份：${dbCount} 个数据库`)) {
        return;
    }

    const startBtn = document.getElementById('start-backup-btn');
    const progressContainer = document.getElementById('progress-container');
    
    startBtn.style.display = 'none';
    progressContainer.style.display = 'block';
    
    setButtonLoading('start-backup-btn', true);

    const result = await fetchApi('/api/backup/start', {
        method: 'POST',
        body: JSON.stringify({ config_id: state.currentConfigId })
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
        if (startBtn) startBtn.style.display = 'none';
        if (progressContainer) progressContainer.style.display = 'block';
        
        const current = status.progress.progress || 0;
        const total = status.progress.total || 0;
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        
        if (progressFill) progressFill.style.width = `${percent}%`;
        if (progressMessage) progressMessage.textContent = status.progress.message || '执行中...';
        if (progressPercent) progressPercent.textContent = `${percent}%`;
    } else {
        if (startBtn) startBtn.style.display = 'inline-block';
        
        if (status.progress.status === 'completed') {
            if (progressFill) progressFill.style.width = '100%';
            if (progressMessage) progressMessage.textContent = status.progress.message || '备份完成';
            if (progressPercent) progressPercent.textContent = '100%';
        } else if (status.progress.status === 'error') {
            if (progressMessage) progressMessage.textContent = status.progress.message || '备份失败';
        }
    }
}

function updateSchedulerStatus(status) {
    const schedulerEl = document.getElementById('scheduler-status');
    const nextRunItem = document.getElementById('next-run-item');
    const nextRunEl = document.getElementById('next-run-time');

    if (schedulerEl) {
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
    }

    if (nextRunItem && nextRunEl) {
        if (status.job_info && status.job_info.next_run_time) {
            nextRunItem.style.display = 'flex';
            nextRunEl.textContent = status.job_info.next_run_time;
        } else {
            nextRunItem.style.display = 'none';
        }
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
    if (!consoleEl) return;

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
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function clearLogs() {
    const consoleEl = document.getElementById('log-console');
    if (!consoleEl) return;
    
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
    if (!tbody) return;

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
