// 运行测试
async function runTest() {
    const btn = document.getElementById('runTestBtn');
    const badge = document.getElementById('statusBadge');
    btn.disabled = true;
    badge.className = 'badge bg-success';
    badge.textContent = '测试中...';

    try {
        const resp = await fetch('/ui/test/run', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            pollTestStatus();
        }
    } catch (e) {
        console.error('触发测试失败:', e);
        resetTestUI();
    }
}

function pollTestStatus() {
    const interval = setInterval(async () => {
        try {
            const resp = await fetch('/ui/test/status');
            const data = await resp.json();
            if (!data.running) {
                clearInterval(interval);
                resetTestUI();
                location.reload();
            }
        } catch (e) {
            clearInterval(interval);
            resetTestUI();
        }
    }, 2000);
}

function resetTestUI() {
    const btn = document.getElementById('runTestBtn');
    const badge = document.getElementById('statusBadge');
    if (btn) btn.disabled = false;
    if (badge) {
        badge.className = 'badge bg-secondary';
        badge.textContent = '空闲';
    }
}

// 从上游拉取模型（现有 provider）
async function fetchModels(providerId) {
    if (!confirm('将从上游拉取模型列表，是否继续?')) return;
    try {
        const resp = await fetch(`/ui/models/fetch/${providerId}`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            alert(`成功拉取 ${data.models.length} 个模型`);
            location.reload();
        }
    } catch (e) {
        alert('拉取失败: ' + e.message);
    }
}

// ======== API Keys 动态管理 ========

function addKeyItem(containerId, keyVal, remarkVal) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'api-key-item row g-2 mb-2 align-items-center';
    div.innerHTML = `
        <div class="col-5">
            <input type="text" class="form-control form-control-sm" placeholder="API Key" data-key-field="key" value="${escapeHtml(keyVal || '')}" required>
        </div>
        <div class="col-4">
            <input type="text" class="form-control form-control-sm" placeholder="备注" data-key-field="remark" value="${escapeHtml(remarkVal || '')}">
        </div>
        <div class="col-3">
            <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeKeyItem(this)">删除</button>
        </div>`;
    container.appendChild(div);
}

function removeKeyItem(btn) {
    const item = btn.closest('.api-key-item');
    if (item) item.remove();
}

function buildApiKeysJson(prefix) {
    const container = document.getElementById(prefix + 'ApiKeysContainer');
    const items = container.querySelectorAll('.api-key-item');
    const keys = [];
    let idx = 0;
    items.forEach(function(item) {
        const keyInput = item.querySelector('[data-key-field="key"]');
        const remarkInput = item.querySelector('[data-key-field="remark"]');
        const keyVal = keyInput ? keyInput.value.trim() : '';
        if (!keyVal) return;
        idx++;
        keys.push({ id: 'k' + idx, key: keyVal, remark: remarkInput ? remarkInput.value.trim() : '' });
    });
    document.getElementById(prefix + 'ApiKeysJson').value = JSON.stringify(keys);
}

// ======== 模型拉取与选择 ========

async function inlineFetchModels(prefix) {
    const url = document.getElementById(prefix + 'Url').value.trim();
    const apiKeysJson = document.getElementById(prefix + 'ApiKeysJson').value;
    // 获取服务类型
    let serviceType = 'openai';
    const serviceTypeEl = document.getElementById(prefix + 'ServiceType');
    if (serviceTypeEl) {
        serviceType = serviceTypeEl.value;
    } else {
        const selectEl = document.querySelector('#' + prefix + 'AddModal [name="service_type"], #addModal [name="service_type"]');
        if (selectEl) serviceType = selectEl.value;
    }
    let apiKey = '';
    try {
        const keys = JSON.parse(apiKeysJson);
        if (keys.length > 0) apiKey = keys[0].key;
    } catch(e) {}
    if (!apiKey) {
        // 尝试从可见的 key input 获取
        const firstInput = document.querySelector('#' + prefix + 'ApiKeysContainer [data-key-field="key"]');
        if (firstInput) apiKey = firstInput.value.trim();
    }
    if (!url || !apiKey) {
        alert('请先填写 URL 和至少一个 API Key');
        return;
    }

    const btnText = document.getElementById(prefix + 'FetchBtnText');
    const originalText = btnText.textContent;
    btnText.textContent = '⏳ 拉取中...';
    btnText.parentElement.disabled = true;

    try {
        const formData = new FormData();
        formData.append('url', url);
        formData.append('api_key', apiKey);
        formData.append('service_type', serviceType);
        const resp = await fetch('/ui/providers/inline-fetch-models', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) {
            renderModelList(prefix, data.models);
        } else {
            alert('拉取失败: ' + (data.error || '未知错误'));
        }
    } catch (e) {
        alert('拉取失败: ' + e.message);
    } finally {
        btnText.textContent = originalText;
        btnText.parentElement.disabled = false;
    }
}

function renderModelList(prefix, modelIds) {
    const container = document.getElementById(prefix + 'ModelList');
    const countLabel = document.getElementById(prefix + 'ModelCount');
    let html = '';
    modelIds.forEach(function(mid) {
        html += `
            <div class="form-check mb-1 model-item">
                <input class="form-check-input model-checkbox" type="checkbox" id="${prefix}_chk_${escapeHtml(mid)}" value="${escapeHtml(mid)}">
                <label class="form-check-label" for="${prefix}_chk_${escapeHtml(mid)}">
                    ${escapeHtml(mid)}
                    <input type="text" class="form-control form-control-sm d-inline-block ms-2" style="width:200px" placeholder="可选别名" data-model-alias="${escapeHtml(mid)}">
                </label>
            </div>`;
    });
    container.innerHTML = html;
    countLabel.textContent = modelIds.length + ' 个模型';
}

function toggleAllModels(prefix, checked) {
    const container = document.getElementById(prefix + 'ModelList');
    const checkboxes = container.querySelectorAll('.model-checkbox');
    checkboxes.forEach(function(cb) { cb.checked = checked; });
}

// ======== 表单提交构建 JSON ========

function buildAddForm() {
    buildApiKeysJson('add');
    buildModelsJson('add');
}

function buildEditForm() {
    buildApiKeysJson('edit');
    buildModelsJson('edit');
    // 修正 form action
    const providerId = document.getElementById('editForm').getAttribute('data-provider-id');
    document.getElementById('editForm').action = '/ui/providers/edit/' + providerId;
}

function buildModelsJson(prefix) {
    const container = document.getElementById(prefix + 'ModelList');
    const items = container.querySelectorAll('.model-item');
    const models = [];
    items.forEach(function(item) {
        const checkbox = item.querySelector('.model-checkbox');
        if (!checkbox) return;
        const aliasInput = item.querySelector('[data-model-alias]');
        const modelId = checkbox.value;
        const alias = aliasInput ? aliasInput.value.trim() : '';
        models.push({
            id: modelId,
            enabled: checkbox.checked,
            alias: alias
        });
    });
    document.getElementById(prefix + 'ModelsJson').value = JSON.stringify(models);
}

// ======== 编辑中转站 ========

function editProvider(id) {
    const scriptEl = document.getElementById('providersData');
    if (!scriptEl) return;
    let providers;
    try { providers = JSON.parse(scriptEl.textContent); } catch(e) { return; }
    const provider = providers.find(function(p) { return p.id === id; });
    if (!provider) return;

    // 设置表单字段
    document.getElementById('editName').value = provider.name || '';
    document.getElementById('editUrl').value = provider.url || '';
    document.getElementById('editRemark').value = provider.remark || '';
    document.getElementById('editServiceType').value = provider.service_type || 'openai';
    document.getElementById('editForm').setAttribute('data-provider-id', id);

    // API Keys
    const keyContainer = document.getElementById('editApiKeysContainer');
    keyContainer.innerHTML = '';
    (provider.api_keys || []).forEach(function(k) {
        addKeyItem('editApiKeysContainer', k.key, k.remark);
    });
    if ((provider.api_keys || []).length === 0) {
        addKeyItem('editApiKeysContainer', '', '');
    }
    buildApiKeysJson('edit');

    // 模型列表
    const existingModels = provider.models || [];
    if (existingModels.length > 0) {
        renderModelListWithState('edit', existingModels);
    } else {
        document.getElementById('editModelList').innerHTML =
            '<p class="text-muted text-center mb-0 py-4">请填写 URL 和 API Key，点击「拉取模型列表」</p>';
        document.getElementById('editModelCount').textContent = '0 个模型';
    }

    var editModal = new bootstrap.Modal(document.getElementById('editModal'));
    editModal.show();
}

function renderModelListWithState(prefix, models) {
    const container = document.getElementById(prefix + 'ModelList');
    const countLabel = document.getElementById(prefix + 'ModelCount');
    let html = '';
    models.forEach(function(m) {
        const alias = m.alias || '';
        html += `
            <div class="form-check mb-1 model-item">
                <input class="form-check-input model-checkbox" type="checkbox" id="${prefix}_chk_${escapeHtml(m.id)}" value="${escapeHtml(m.id)}" ${m.enabled ? 'checked' : ''}>
                <label class="form-check-label" for="${prefix}_chk_${escapeHtml(m.id)}">
                    ${escapeHtml(m.id)}
                    <input type="text" class="form-control form-control-sm d-inline-block ms-2" style="width:200px" placeholder="可选别名" data-model-alias="${escapeHtml(m.id)}" value="${escapeHtml(alias)}">
                </label>
            </div>`;
    });
    container.innerHTML = html;
    countLabel.textContent = models.length + ' 个模型';
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ======== 单模型测试（模型管理页面） ========

async function testSingleModel(providerId, modelId) {
    const modal = new bootstrap.Modal(document.getElementById('testResultModal'));
    document.getElementById('testResultModelName').textContent = modelId;
    document.getElementById('testResultLoading').style.display = '';
    document.getElementById('testResultContent').style.display = 'none';
    modal.show();

    try {
        const formData = new FormData();
        formData.append('provider_id', providerId);
        formData.append('model_id', modelId);
        const resp = await fetch('/ui/models/test-single', { method: 'POST', body: formData });
        const data = await resp.json();
        document.getElementById('testResultLoading').style.display = 'none';
        const content = document.getElementById('testResultContent');

        let html = '<div class="row">';
        data.results.forEach(function(r) {
            const statusHtml = r.success
                ? '<span class="text-success">✓ 可用</span>'
                : '<span class="text-danger">✗ 不可用</span>';
            html += '<div class="col-12 mb-3 border rounded p-3">';
            html += '<div class="row g-2">';
            html += '<div class="col-md-3"><strong>中转站：</strong>' + escapeHtml(r.provider_name) + '</div>';
            html += '<div class="col-md-2"><strong>Key：</strong>' + escapeHtml(r.key_id) + '</div>';
            html += '<div class="col-md-2"><strong>延迟：</strong>' + r.latency_ms.toFixed(0) + ' ms</div>';
            html += '<div class="col-md-2"><strong>状态：</strong>' + statusHtml + '</div>';
            if (data.best && data.best.key_id === r.key_id) {
                html += '<div class="col-md-1"><span class="badge bg-success">最优</span></div>';
            }
            html += '</div>';
            if (!r.success && r.error_message) {
                html += '<div class="mt-2"><strong>错误：</strong><pre class="text-danger mb-0">' + escapeHtml(r.error_message) + '</pre></div>';
            }
            html += '<ul class="nav nav-tabs mt-2" role="tablist">';
            html += '<li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#req-' + r.key_id + '" type="button">请求</button></li>';
            html += '<li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#resp-' + r.key_id + '" type="button">响应</button></li>';
            html += '</ul>';
            html += '<div class="tab-content mt-1">';
            html += '<div class="tab-pane fade show active" id="req-' + r.key_id + '"><pre class="bg-light p-2 rounded" style="max-height:250px;overflow:auto;font-size:11px">' + escapeHtml(r.request_body) + '</pre></div>';
            html += '<div class="tab-pane fade" id="resp-' + r.key_id + '"><pre class="bg-light p-2 rounded" style="max-height:250px;overflow:auto;font-size:11px">' + escapeHtml(r.response_body) + '</pre></div>';
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';
        content.innerHTML = html;
        content.style.display = '';
    } catch (e) {
        document.getElementById('testResultLoading').style.display = 'none';
        document.getElementById('testResultContent').innerHTML = '<div class="alert alert-danger">测试失败：' + e.message + '</div>';
        document.getElementById('testResultContent').style.display = '';
    }
}

function toggleAllModelsInGroup(prefix, checked) {
    const checkboxes = document.querySelectorAll('[id^="' + prefix + '"]');
    checkboxes.forEach(function(cb) {
        if (cb.classList.contains('model-checkbox')) {
            cb.checked = checked;
        }
    });
}
