document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');
    const loadingIndicator = document.getElementById('loading-indicator');
    const conversationList = document.getElementById('conversation-list');
    const newChatButton = document.getElementById('new-chat-button');
    const welcomeMessage = document.getElementById('welcome-message');

    let currentConversationId = null;

    function clearChatBox() {
        // Hapus semua elemen anak dari chatBox
        while (chatBox.firstChild) {
            chatBox.removeChild(chatBox.firstChild);
        }
        // Tambahkan kembali loading indicator yang tersembunyi
        chatBox.appendChild(loadingIndicator);
    }

    function addMessage(sender, message) {
        // ... (Fungsi ini tidak berubah) ...
        const messageDiv = document.createElement('div');
        messageDiv.className = 'flex items-start gap-3';
        let contentHTML = message;
        if (sender === 'AI') {
            contentHTML = marked.parse(message);
            messageDiv.innerHTML = `<div class="bg-sky-500 rounded-full p-2 text-white text-sm font-bold">AI</div><div class="bg-slate-800 rounded-lg p-3 max-w-2xl overflow-x-auto">${contentHTML}</div>`;
        } else {
            messageDiv.classList.add('justify-end');
            messageDiv.innerHTML = `<div class="bg-slate-700 rounded-lg p-3 max-w-lg"><p>${message}</p></div><div class="bg-indigo-500 rounded-full p-2 text-white text-sm font-bold">You</div>`;
        }
        // Sisipkan sebelum loading indicator
        chatBox.insertBefore(messageDiv, loadingIndicator);
        messageDiv.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    async function loadConversations() {
        // ... (Fungsi ini tidak berubah) ...
        const response = await fetch('/get_conversations');
        const conversations = await response.json();
        conversationList.innerHTML = '';
        conversations.forEach(conv => {
            const li = document.createElement('li');
            li.innerHTML = `<button data-id="${conv.id}" class="w-full text-left p-2 rounded-md hover:bg-slate-700 truncate">${conv.title}</button>`;
            conversationList.appendChild(li);
        });
    }

    async function loadConversationHistory(id) {
        // ... (Fungsi ini tidak berubah) ...
        clearChatBox();
        currentConversationId = id;
        const response = await fetch(`/get_history/${id}`);
        const history = await response.json();
        history.forEach(msg => {
            const sender = msg.role === 'model' ? 'AI' : 'You';
            addMessage(sender, msg.parts[0]);
        });
        document.querySelectorAll('#conversation-list button').forEach(btn => {
            btn.classList.toggle('bg-slate-700', btn.dataset.id === id);
        });
    }

    conversationList.addEventListener('click', (e) => {
        // ... (Fungsi ini tidak berubah) ...
        const button = e.target.closest('button');
        if (button) {
            const id = button.dataset.id;
            loadConversationHistory(id);
        }
    });
    
    // Fungsi untuk memulai percakapan baru
    async function startNewChat() {
        const response = await fetch('/new_chat', { method: 'POST' });
        const data = await response.json();
        currentConversationId = data.conversation_id;
        clearChatBox();
        addMessage('AI', 'Percakapan baru dimulai. Silakan ketik pesan Anda.');
        loadConversations();
        document.querySelectorAll('#conversation-list button').forEach(btn => btn.classList.remove('bg-slate-700'));
    }

    newChatButton.addEventListener('click', startNewChat);

    // --- PERBAIKAN UTAMA ADA DI SINI ---
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = userInput.value.trim();
        if (!message) return; // Jika pesan kosong, hentikan

        // Jika belum ada percakapan aktif, buat dulu secara otomatis
        if (!currentConversationId) {
            const newChatResponse = await fetch('/new_chat', { method: 'POST' });
            const newChatData = await newChatResponse.json();
            currentConversationId = newChatData.conversation_id;
            clearChatBox(); // Bersihkan pesan "selamat datang" awal
        }

        addMessage('You', message);
        userInput.value = '';
        loadingIndicator.classList.remove('hidden');
        chatBox.scrollTop = chatBox.scrollHeight;

        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message, conversation_id: currentConversationId }),
            });
            const data = await response.json();
            loadingIndicator.classList.add('hidden');

            if (data.error) {
                addMessage('AI', `Error: ${data.error}`);
            } else {
                addMessage('AI', data.response);
                // Cek apakah ini pesan pertama dalam percakapan
                const isFirstMessage = chatBox.querySelectorAll('.justify-end').length === 1;
                if (isFirstMessage) {
                    loadConversations(); // Muat ulang daftar history untuk menampilkan judul baru
                }
            }
        } catch (error) {
            loadingIndicator.classList.add('hidden');
            addMessage('AI', `Terjadi masalah koneksi.`);
        }
    });

    loadConversations();
});