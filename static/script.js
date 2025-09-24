document.addEventListener('DOMContentLoaded', () => {
    // <-- Dapatkan elemen baru untuk input file dan pratinjau -->
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const imageInput = document.getElementById('image-input'); // Elemen input file
    const imagePreviewContainer = document.getElementById('image-preview-container'); // Kontainer untuk pratinjau
    const imagePreview = document.getElementById('image-preview'); // Gambar pratinjau
    const removeImageButton = document.getElementById('remove-image-button'); // Tombol hapus pratinjau

    const chatBox = document.getElementById('chat-box');
    const loadingIndicator = document.getElementById('loading-indicator');
    const conversationList = document.getElementById('conversation-list');
    const newChatButton = document.getElementById('new-chat-button');
    const welcomeMessage = document.getElementById('welcome-message');

    let currentConversationId = null;

    function clearChatBox() {
        while (chatBox.firstChild) {
            chatBox.removeChild(chatBox.firstChild);
        }
        chatBox.appendChild(loadingIndicator);
    }
    
    // <-- Fungsi baru untuk menambahkan pesan PENGGUNA dengan pratinjau gambar -->
    function addUserMessageWithImage(message, imageFile) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'flex items-start gap-3 justify-end';

        let imageHTML = '';
        if (imageFile) {
            // Gunakan URL.createObjectURL untuk menampilkan gambar lokal sebelum diunggah
            const imageURL = URL.createObjectURL(imageFile);
            imageHTML = `<img src="${imageURL}" alt="Image Preview" class="max-w-xs rounded-lg mt-2"/>`;
        }

        const textHTML = message ? `<p>${message}</p>` : '';

        messageDiv.innerHTML = `
            <div class="bg-slate-700 rounded-lg p-3 max-w-lg">
                ${textHTML}
                ${imageHTML}
            </div>
            <div class="bg-indigo-500 rounded-full p-2 text-white text-sm font-bold self-start">You</div>
        `;
        chatBox.insertBefore(messageDiv, loadingIndicator);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function addMessage(sender, message) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'flex items-start gap-3';
        let contentHTML = message;
        
        if (sender === 'AI') {
            contentHTML = marked.parse(message); // Pastikan library 'marked' sudah di-load
            messageDiv.innerHTML = `
                <div class="bg-sky-500 rounded-full p-2 text-white text-sm font-bold self-start">AI</div>
                <div class="bg-slate-800 rounded-lg p-3 max-w-2xl overflow-x-auto prose prose-invert">
                    ${contentHTML}
                </div>`;
        } else { // Ini hanya akan digunakan untuk memuat history
            messageDiv.classList.add('justify-end');
            messageDiv.innerHTML = `
                <div class="bg-slate-700 rounded-lg p-3 max-w-lg"><p>${message}</p></div>
                <div class="bg-indigo-500 rounded-full p-2 text-white text-sm font-bold self-start">You</div>`;
        }

        chatBox.insertBefore(messageDiv, loadingIndicator);
        messageDiv.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block)); // Pastikan 'hljs' sudah di-load
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    async function loadConversations() {
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
        welcomeMessage.classList.add('hidden');
        chatBox.classList.remove('hidden');
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
        const button = e.target.closest('button');
        if (button) {
            loadConversationHistory(button.dataset.id);
        }
    });
    
    async function startNewChat() {
        const response = await fetch('/new_chat', { method: 'POST' });
        const data = await response.json();
        currentConversationId = data.conversation_id;
        welcomeMessage.classList.add('hidden');
        chatBox.classList.remove('hidden');
        clearChatBox();
        loadConversations();
        document.querySelectorAll('#conversation-list button').forEach(btn => btn.classList.remove('bg-slate-700'));
    }

    newChatButton.addEventListener('click', startNewChat);

    // <-- Fitur pratinjau gambar sebelum dikirim -->
    imageInput.addEventListener('change', () => {
        if (imageInput.files && imageInput.files[0]) {
            const reader = new FileReader();
            reader.onload = (e) => {
                imagePreview.src = e.target.result;
                imagePreviewContainer.classList.remove('hidden');
            };
            reader.readAsDataURL(imageInput.files[0]);
        }
    });

    removeImageButton.addEventListener('click', () => {
        imageInput.value = ''; // Hapus file yang dipilih
        imagePreviewContainer.classList.add('hidden');
    });

    // --- [PERBAIKAN UTAMA] Logika Pengiriman Form ---
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const message = userInput.value.trim();
        const imageFile = imageInput.files[0];

        // <-- Validasi: Kirim hanya jika ada pesan teks atau gambar -->
        if (!message && !imageFile) {
            return;
        }

        if (!currentConversationId) {
            await startNewChat();
        }

        // Tampilkan pesan pengguna di UI
        addUserMessageWithImage(message, imageFile);
        
        // <-- Buat objek FormData untuk mengirim file dan teks -->
        const formData = new FormData();
        formData.append('conversation_id', currentConversationId);
        if (message) {
            formData.append('message', message);
        }
        if (imageFile) {
            formData.append('image', imageFile);
        }

        // Reset input setelah ditampilkan
        userInput.value = '';
        imageInput.value = '';
        imagePreviewContainer.classList.add('hidden');
        
        loadingIndicator.classList.remove('hidden');
        chatBox.scrollTop = chatBox.scrollHeight;

        try {
            // <-- Kirim request menggunakan FormData -->
            const response = await fetch('/chat', {
                method: 'POST',
                // HAPUS header 'Content-Type', browser akan mengaturnya secara otomatis untuk FormData
                body: formData,
            });

            const data = await response.json();
            loadingIndicator.classList.add('hidden');

            if (data.error) {
                addMessage('AI', `Error: ${data.error}`);
            } else {
                addMessage('AI', data.response);
                const isFirstMessage = chatBox.querySelectorAll('.justify-end').length === 1;
                if (isFirstMessage) {
                    loadConversations();
                }
            }
        } catch (error) {
            loadingIndicator.classList.add('hidden');
            addMessage('AI', 'Terjadi masalah koneksi atau kesalahan server.');
            console.error('Fetch error:', error);
        }
    });

    loadConversations();
});