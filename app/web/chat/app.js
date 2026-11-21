let messages = [];
let currentModel = '';
let isGenerating = false;
let authToken = '';

const chatContainer = document.getElementById('chatContainer');
const messagesDiv = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const welcomeScreen = document.getElementById('welcomeScreen');
const newChatBtn = document.getElementById('newChatBtn');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');
const modelSelect = document.getElementById('modelSelect');
const chatLoginForm = document.getElementById('chatLoginForm');
const chatIdentity = document.getElementById('chatIdentity');

marked.setOptions({ breaks: true, gfm: true });

function authHeaders(extra = {}) {
    const headers = { ...extra };
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
}

function showLogin(message = '') {
    if (chatLoginForm) chatLoginForm.hidden = false;
    if (chatIdentity) chatIdentity.hidden = true;
    const error = document.getElementById('chatAuthError');
    if (error) {
        error.textContent = message;
        error.hidden = !message;
    }
    sendBtn.disabled = true;
}

function setIdentity(me) {
    if (chatLoginForm) chatLoginForm.hidden = true;
    if (chatIdentity) chatIdentity.hidden = false;
    const error = document.getElementById('chatAuthError');
    if (error) error.hidden = true;
    const name = document.getElementById('chatIdentityName');
    if (name) name.textContent = `${me.display_name} · ${me.role}`;
    const footer = document.querySelector('.footer-text');
    if (footer) footer.textContent = `Gantry AI · ${me.display_name}`;
    sendBtn.disabled = userInput.value.trim() === '' || isGenerating || !authToken;
}

async function loadSession() {
    if (!authToken) {
        showLogin();
        return false;
    }
    const res = await fetch('/api/v1/auth/me', { headers: authHeaders() });
    if (!res.ok) {
        authToken = '';
        showLogin('نشست منقضی شد. دوباره وارد شوید.');
        return false;
    }
    setIdentity(await res.json());
    return true;
}

async function login(event) {
    event.preventDefault();
    const username = document.getElementById('chatUsername')?.value || '';
    const password = document.getElementById('chatPassword')?.value || '';
    try {
        const res = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(payload?.error?.message || 'ورود ناموفق بود.');
        }
        authToken = payload.access_token;
        const field = document.getElementById('chatPassword');
        if (field) field.value = '';
        if (await loadSession()) await loadModels();
    } catch (e) {
        showLogin(e.message);
    }
}

function logout() {
    authToken = '';
    showLogin();
}

async function loadModels() {
    try {
        const res = await fetch('/api/v1/chat/models', { headers: authHeaders() });
        const data = await res.json();
        modelSelect.innerHTML = '';
        (data.models || []).forEach((model) => {
            const opt = document.createElement('option');
            opt.value = model;
            opt.textContent = model;
            if (model === data.default) opt.selected = true;
            modelSelect.appendChild(opt);
        });
        currentModel = modelSelect.value || data.default;
    } catch {
        const opt = document.createElement('option');
        opt.value = 'llama-3.1-8b-instant';
        opt.textContent = 'llama-3.1-8b-instant';
        opt.selected = true;
        modelSelect.appendChild(opt);
        currentModel = opt.value;
    }
}

modelSelect.addEventListener('change', () => { currentModel = modelSelect.value; });

function loadHistory() {
    try {
        const saved = localStorage.getItem('gantry_chat_history');
        if (!saved) return;
        messages = JSON.parse(saved);
        if (messages.length > 0) {
            welcomeScreen.style.display = 'none';
            renderMessages();
        }
    } catch { messages = []; }
}

function saveHistory() {
    localStorage.setItem('gantry_chat_history', JSON.stringify(messages));
}

function autoResize() {
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 220) + 'px';
}

userInput.addEventListener('input', () => {
    autoResize();
    sendBtn.disabled = userInput.value.trim() === '' || isGenerating;
});

userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) sendMessage();
    }
});

sendBtn.addEventListener('click', sendMessage);

newChatBtn.addEventListener('click', () => {
    if (!confirm('گفتگوی جدید شروع شود؟')) return;
    messages = [];
    localStorage.removeItem('gantry_chat_history');
    welcomeScreen.style.display = 'flex';
    messagesDiv.innerHTML = '';
    userInput.value = '';
    autoResize();
    sendBtn.disabled = true;
    userInput.focus();
});

clearHistoryBtn.addEventListener('click', () => {
    if (!confirm('تمام تاریخچه گفتگو پاک شود؟')) return;
    messages = [];
    localStorage.removeItem('gantry_chat_history');
    welcomeScreen.style.display = 'flex';
    messagesDiv.innerHTML = '';
});

document.querySelectorAll('.suggestion-card').forEach((card) => {
    card.addEventListener('click', () => {
        userInput.value = card.getAttribute('data-prompt');
        autoResize();
        sendBtn.disabled = false;
        userInput.focus();
    });
});

function renderMessages() {
    messagesDiv.innerHTML = '';
    messages.forEach((msg) => messagesDiv.appendChild(createMessageElement(msg.role, msg.content)));
    scrollToBottom();
}

function createMessageElement(role, content) {
    const wrap = document.createElement('div');
    wrap.className = `message ${role === 'user' ? 'user-message' : 'assistant-message'}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = role === 'user' ? '<i class="bi bi-person-fill"></i>' : '<i class="bi bi-cpu"></i>';

    const contentWrap = document.createElement('div');
    contentWrap.className = 'message-content';

    const header = document.createElement('div');
    header.className = 'message-header';
    const roleSpan = document.createElement('span');
    roleSpan.className = 'message-role';
    roleSpan.textContent = role === 'user' ? 'شما' : 'Gantry AI';
    header.appendChild(roleSpan);

    const text = document.createElement('div');
    text.className = 'message-text';
    if (role === 'assistant') {
        text.innerHTML = DOMPurify.sanitize(marked.parse(content || ''));
    } else {
        text.textContent = content;
    }

    contentWrap.appendChild(header);
    contentWrap.appendChild(text);
    wrap.appendChild(avatar);
    wrap.appendChild(contentWrap);
    return wrap;
}

function addTyping() {
    const wrap = document.createElement('div');
    wrap.className = 'message assistant-message';
    wrap.id = 'typingIndicator';
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = '<i class="bi bi-cpu"></i>';
    const contentWrap = document.createElement('div');
    contentWrap.className = 'message-content';
    const header = document.createElement('div');
    header.className = 'message-header';
    const roleSpan = document.createElement('span');
    roleSpan.className = 'message-role';
    roleSpan.textContent = 'Gantry AI';
    header.appendChild(roleSpan);
    const dots = document.createElement('div');
    dots.className = 'typing-indicator';
    dots.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
    contentWrap.appendChild(header);
    contentWrap.appendChild(dots);
    wrap.appendChild(avatar);
    wrap.appendChild(contentWrap);
    messagesDiv.appendChild(wrap);
    scrollToBottom();
}

function removeTyping() {
    const el = document.getElementById('typingIndicator');
    if (el) el.remove();
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

async function sendMessage() {
    const content = userInput.value.trim();
    if (!content || isGenerating) return;
    if (!authToken) {
        showLogin('برای ارسال پیام ابتدا وارد شوید.');
        return;
    }

    welcomeScreen.style.display = 'none';

    messages.push({ role: 'user', content });
    saveHistory();
    messagesDiv.appendChild(createMessageElement('user', content));

    userInput.value = '';
    autoResize();
    sendBtn.disabled = true;
    isGenerating = true;
    scrollToBottom();

    addTyping();

    try {
        const res = await fetch('/api/v1/chat/completions', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                messages: messages,
                model: currentModel,
                temperature: 0.7,
                max_tokens: 2048,
            }),
        });

        removeTyping();

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            if (res.status === 401 && authToken) {
                authToken = '';
                showLogin('نشست منقضی شد. دوباره وارد شوید.');
            }
            throw new Error(err?.error?.message || err.detail || 'خطا در ارتباط با سرور');
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let assistantText = '';

        const wrap = createMessageElement('assistant', '');
        messagesDiv.appendChild(wrap);
        const textDiv = wrap.querySelector('.message-text');

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value);
            for (const line of chunk.split('\n')) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);
                if (data === '[DONE]') break;
                try {
                    const parsed = JSON.parse(data);
                    if (parsed.error) {
                        textDiv.textContent = 'خطا: ' + parsed.error;
                        break;
                    }
                    const delta = parsed.choices?.[0]?.delta?.content || '';
                    if (delta) {
                        assistantText += delta;
                        textDiv.innerHTML = DOMPurify.sanitize(marked.parse(assistantText));
                        scrollToBottom();
                    }
                } catch {}
            }
        }

        if (assistantText) {
            messages.push({ role: 'assistant', content: assistantText });
            saveHistory();
        }
    } catch (e) {
        removeTyping();
        messagesDiv.appendChild(createMessageElement('assistant', 'متأسفم، خطایی رخ داد: ' + e.message));
    }

    isGenerating = false;
    sendBtn.disabled = userInput.value.trim() === '';
    scrollToBottom();
}

if (chatLoginForm) chatLoginForm.addEventListener('submit', login);
document.getElementById('chatLogoutBtn')?.addEventListener('click', logout);

async function boot() {
    const signedIn = await loadSession();
    if (signedIn) await loadModels();
    loadHistory();
    userInput.focus();
}

boot();
