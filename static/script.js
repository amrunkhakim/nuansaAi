document.addEventListener('DOMContentLoaded', () => {
    // --- Ambil semua elemen dari DOM ---
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const imageInput = document.getElementById('image-input');
    const submitBtn = chatForm.querySelector('button[type="submit"]');

    const imagePreviewContainer = document.getElementById('image-preview-container');
    const imagePreview = document.getElementById('image-preview');
    const removeImageButton = document.getElementById('remove-image-button');

    const chatBox = document.getElementById('chat-box');
    const conversationList = document.getElementById('conversation-list');
    const newChatButton = document.getElementById('new-chat-button');
    const welcomeMessage = document.getElementById('welcome-message');

    // [PENAMBAHAN] Ambil elemen untuk slider temperature
    const temperatureSlider = document.getElementById('temperature-slider');
    const temperatureValue = document.getElementById('temperature-value');

    // Untuk mobile
    const menuToggle = document.getElementById('menu-toggle');
    const sidebar = document.querySelector('aside');

    let currentConversationId = null;
    let isGenerating = false;

    // --- Fungsi Helper ---
    function clearChatBox() {
        chatBox.innerHTML = '';
    }

    function toggleSubmitButton() {
        const hasText = userInput.value.trim().length > 0;
        const hasImage = imageInput.files.length > 0;
        submitBtn.disabled = !hasText && !hasImage;
    }
    
    function addUserMessageWithImage(message, imageFile) {
        welcomeMessage.classList.add('hidden');
        const messageDiv = document.createElement('div');
        messageDiv.className = 'flex items-start gap-3 justify-end';

        let imageHTML = '';
        if (imageFile) {
            const imageURL = URL.createObjectURL(imageFile);
            imageHTML = `<img src="${imageURL}" alt="Image Preview" class="max-w-xs rounded-lg mt-2"/>`;
        }
        const textHTML = message ? `<p class="whitespace-pre-wrap">${message}</p>` : '';

        messageDiv.innerHTML = `
            <div class="bg-slate-700 rounded-lg p-3 max-w-lg">
                ${textHTML}
                ${imageHTML}
            </div>
            <div class="bg-indigo-500 rounded-full p-2 text-white text-sm font-bold self-start">You</div>
        `;
        chatBox.appendChild(messageDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function addHistoryMessage(sender, message) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'flex items-start gap-3';
        
        if (sender === 'AI') {
            const contentHTML = marked.parse(message);
            messageDiv.innerHTML = `
                <div class="bg-sky-500 rounded-full p-2 text-white text-sm font-bold self-start">AI</div>
                <div class="bg-slate-800 rounded-lg p-3 max-w-2xl overflow-x-auto prose prose-invert">${contentHTML}</div>
            `;
        } else {
            messageDiv.classList.add('justify-end');
            messageDiv.innerHTML = `
                <div class="bg-slate-700 rounded-lg p-3 max-w-lg"><p class="whitespace-pre-wrap">${message}</p></div>
                <div class="bg-indigo-500 rounded-full p-2 text-white text-sm font-bold self-start">You</div>
            `;
        }
        chatBox.appendChild(messageDiv);
        chatBox.querySelectorAll('pre').forEach(addCopyButton);
        chatBox.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
        chatBox.scrollTop = chatBox.scrollHeight;
    }
    
    function addCopyButton(preElement) {
        const copyButton = document.createElement('button');
        copyButton.className = 'copy-code-btn';
        copyButton.innerText = 'Salin';
        preElement.appendChild(copyButton);
    }

    // --- Logika Utama Aplikasi ---
    async function loadConversations() {
        try {
            const response = await fetch('/get_conversations');
            const conversations = await response.json();
            conversationList.innerHTML = '';
            conversations.forEach(conv => {
                const li = document.createElement('li');
                li.innerHTML = `<button data-id="${conv.id}" class="w-full text-left p-2 rounded-md hover:bg-slate-700 truncate">${conv.title}</button>`;
                conversationList.appendChild(li);
            });
        } catch (error) {
            console.error("Gagal memuat percakapan:", error);
        }
    }

    async function loadConversationHistory(id) {
        if (isGenerating) return;
        welcomeMessage.classList.add('hidden');
        clearChatBox();
        currentConversationId = id;
        try {
            const response = await fetch(`/get_history/${id}`);
            const history = await response.json();
            history.forEach(msg => {
                const sender = msg.role === 'model' ? 'AI' : 'You';
                addHistoryMessage(sender, msg.parts[0]);
            });
            document.querySelectorAll('#conversation-list button').forEach(btn => {
                btn.classList.toggle('bg-slate-700', btn.dataset.id === id);
            });
        } catch (error) {
            console.error("Gagal memuat riwayat:", error);
        }
    }

    async function startNewChat() {
        if (isGenerating) return;
        currentConversationId = null;
        clearChatBox();
        welcomeMessage.classList.remove('hidden');
        userInput.value = '';
        imageInput.value = '';
        imagePreviewContainer.classList.add('hidden');
        toggleSubmitButton();
        await loadConversations();
        document.querySelectorAll('#conversation-list button').forEach(btn => btn.classList.remove('bg-slate-700'));
    }

    // --- Event Listeners ---
    newChatButton.addEventListener('click', startNewChat);
    conversationList.addEventListener('click', (e) => {
        const button = e.target.closest('button');
        if (button) loadConversationHistory(button.dataset.id);
    });

    imageInput.addEventListener('change', () => {
        if (imageInput.files && imageInput.files[0]) {
            const reader = new FileReader();
            reader.onload = (e) => {
                imagePreview.src = e.target.result;
                imagePreviewContainer.classList.remove('hidden');
            };
            reader.readAsDataURL(imageInput.files[0]);
        }
        toggleSubmitButton();
    });

    removeImageButton.addEventListener('click', () => {
        imageInput.value = '';
        imagePreviewContainer.classList.add('hidden');
        toggleSubmitButton();
    });
    
    userInput.addEventListener('input', toggleSubmitButton);
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    });

    // [PENAMBAHAN] Event listener untuk memperbarui tampilan nilai slider
    temperatureSlider.addEventListener('input', () => {
        if (temperatureValue) {
            temperatureValue.innerText = parseFloat(temperatureSlider.value).toFixed(1);
        }
    });

    // [LOGIKA UTAMA] Pengiriman Form dengan STREAMING
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = userInput.value.trim();
        const imageFile = imageInput.files[0];
        if (!message && !imageFile || isGenerating) return;

        isGenerating = true;
        toggleSubmitButton();

        if (!currentConversationId) {
            const response = await fetch('/new_chat', { method: 'POST' });
            const data = await response.json();
            currentConversationId = data.conversation_id;
        }

        addUserMessageWithImage(message, imageFile);
        
        const formData = new FormData();
        formData.append('conversation_id', currentConversationId);
        
        // [PENAMBAHAN] Kirim nilai temperature ke backend
        formData.append('temperature', temperatureSlider.value);

        if (message) formData.append('message', message);
        if (imageFile) formData.append('image', imageFile);

        userInput.value = '';
        userInput.style.height = 'auto';
        imageInput.value = '';
        imagePreviewContainer.classList.add('hidden');

        try {
            const response = await fetch('/chat', { method: 'POST', body: formData });
            if (!response.ok) throw new Error(await response.text());

            const aiMessageContainer = document.createElement('div');
            aiMessageContainer.className = 'flex items-start gap-3';
            aiMessageContainer.innerHTML = `
                <div class="bg-sky-500 rounded-full p-2 text-white text-sm font-bold self-start">AI</div>
                <div class="bg-slate-800 rounded-lg p-3 max-w-2xl overflow-x-auto prose prose-invert"></div>
            `;
            chatBox.appendChild(aiMessageContainer);
            const responseDiv = aiMessageContainer.querySelector('.prose');

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullResponse = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                fullResponse += decoder.decode(value, { stream: true });
                responseDiv.innerHTML = marked.parse(fullResponse + "▐");
                chatBox.scrollTop = chatBox.scrollHeight;
            }
            
            responseDiv.innerHTML = marked.parse(fullResponse);
            responseDiv.querySelectorAll('pre').forEach(addCopyButton);
            responseDiv.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
            
            const isFirstMessage = chatBox.querySelectorAll('.justify-end').length === 1;
            if (isFirstMessage) await loadConversations();

        } catch (error) {
            addHistoryMessage('AI', `Terjadi kesalahan: ${error.message}`);
        } finally {
            isGenerating = false;
            toggleSubmitButton();
        }
    });

    chatBox.addEventListener('click', function(e) {
        if (e.target && e.target.classList.contains('copy-code-btn')) {
            const pre = e.target.closest('pre');
            const code = pre.querySelector('code').innerText;
            navigator.clipboard.writeText(code).then(() => {
                e.target.innerText = 'Disalin!';
                setTimeout(() => { e.target.innerText = 'Salin'; }, 2000);
            });
        }
    });

    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.toggle('hidden');
            sidebar.classList.toggle('md:flex');
        });
    }

    // --- Inisialisasi ---
    loadConversations();
    toggleSubmitButton();
});