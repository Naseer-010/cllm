document.addEventListener('DOMContentLoaded', () => {
    const chatContainer = document.getElementById('chat-container');
    const messagesEl = document.getElementById('messages');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const modelNameEl = document.getElementById('model-name');
    const typingIndicator = document.getElementById('typing-indicator');
    
    const minimizeBtn = document.getElementById('minimize-btn');
    const closeBtn = document.getElementById('close-btn');
    const minimizeOverlay = document.getElementById('minimize-overlay');
    const restoreBtn = document.getElementById('restore-btn');

    let chatHistory = [];
    let isWaitingForResponse = false;

    // Fetch model info
    fetch('/api/model-info')
        .then(res => res.json())
        .then(data => {
            if(data && data.name) {
                modelNameEl.textContent = data.name;
            }
        })
        .catch(err => {
            console.error('Error fetching model info:', err);
            modelNameEl.textContent = 'Unknown Model';
        });

    // Auto-grow textarea
    messageInput.addEventListener('input', () => {
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 150) + 'px';
        sendBtn.disabled = messageInput.value.trim().length === 0 || isWaitingForResponse;
    });

    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    // Window controls
    minimizeBtn.addEventListener('click', () => {
        minimizeOverlay.classList.remove('hidden');
    });

    restoreBtn.addEventListener('click', () => {
        minimizeOverlay.classList.add('hidden');
    });

    closeBtn.addEventListener('click', async () => {
        if (confirm('End chat session?')) {
            try {
                await fetch('/api/shutdown', { method: 'POST' });
                document.body.innerHTML = '<div style="display:flex;justify-content:center;align-items:center;height:100%;"><p>Session ended. You can close this tab.</p></div>';
            } catch (err) {
                console.error('Error shutting down:', err);
                alert('Failed to shutdown server.');
            }
        }
    });

    function getTimestamp() {
        const now = new Date();
        let hours = now.getHours();
        let minutes = now.getMinutes();
        const ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12; 
        minutes = minutes < 10 ? '0'+minutes : minutes;
        return hours + ':' + minutes + ' ' + ampm;
    }

    async function sendMessage() {
        const content = messageInput.value.trim();
        if (!content || isWaitingForResponse) return;

        // Reset input
        messageInput.value = '';
        messageInput.style.height = 'auto';
        sendBtn.disabled = true;

        // Add user message
        const userMsg = { role: 'user', content };
        appendMessage(userMsg);
        
        const historyToSend = [...chatHistory];
        chatHistory.push(userMsg);

        isWaitingForResponse = true;
        
        messagesEl.appendChild(typingIndicator); // Move indicator to bottom
        typingIndicator.classList.remove('hidden');
        scrollToBottom();

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: content, history: historyToSend })
            });

            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

            typingIndicator.classList.add('hidden');
            
            // Create assistant message element
            const assistantMsgEl = createMessageElement('assistant');
            const contentContainer = assistantMsgEl.querySelector('.message-content');
            messagesEl.appendChild(assistantMsgEl);
            
            let assistantContent = '';
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.substring(6).trim();
                        if (!dataStr) continue;
                        
                        try {
                            const data = JSON.parse(dataStr);
                            if (data.token) {
                                assistantContent += data.token;
                                contentContainer.innerHTML = parseMarkdown(assistantContent);
                                setupCopyButtons(contentContainer);
                                scrollToBottom();
                            }
                            if (data.done) {
                                chatHistory.push({ role: 'assistant', content: assistantContent });
                                isWaitingForResponse = false;
                                sendBtn.disabled = messageInput.value.trim().length === 0;
                                messageInput.focus();
                                return;
                            }
                        } catch (e) {
                            console.error('Error parsing SSE data:', e, dataStr);
                        }
                    }
                }
            }
            
            // Fallback in case stream ends without done:true
            chatHistory.push({ role: 'assistant', content: assistantContent });
            
        } catch (error) {
            console.error('Error during chat:', error);
            typingIndicator.classList.add('hidden');
            
            const errorMsg = { role: 'assistant', content: 'Error: Failed to get response.' };
            appendMessage(errorMsg);
        } finally {
            isWaitingForResponse = false;
            sendBtn.disabled = messageInput.value.trim().length === 0;
            messageInput.focus();
        }
    }

    function appendMessage(msg) {
        const msgEl = createMessageElement(msg.role);
        msgEl.querySelector('.message-content').innerHTML = parseMarkdown(msg.content);
        setupCopyButtons(msgEl);
        messagesEl.appendChild(msgEl);
        scrollToBottom();
    }

    function createMessageElement(role) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        const timeDiv = document.createElement('div');
        timeDiv.className = 'timestamp';
        timeDiv.textContent = getTimestamp();
        
        div.appendChild(contentDiv);
        div.appendChild(timeDiv);
        return div;
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function parseMarkdown(text) {
        if (!text) return '';
        
        // Escape HTML
        let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        
        // Code blocks: ```language\ncode\n```
        html = html.replace(/```([\s\S]*?)```/g, (match, code) => {
            const lines = code.split('\n');
            if(lines[0] && !lines[0].includes(' ') && lines.length > 1) {
                lines.shift();
            }
            const cleanCode = lines.join('\n').trim() || code.trim();
            
            return `<div class="code-block-wrapper">
                <button class="copy-btn">Copy</button>
                <pre><code>${cleanCode}</code></pre>
            </div>`;
        });
        
        // Inline code: `code`
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        
        // Bold: **text**
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Italic: *text*
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        
        // Lists & Paragraphs
        const lines = html.split('\n');
        let inList = false;
        let listType = '';
        let parsedLines = [];
        
        for (let i = 0; i < lines.length; i++) {
            let line = lines[i];
            
            if (line.includes('<div class="code-block-wrapper">')) {
                parsedLines.push(line);
                while(i + 1 < lines.length && !lines[i + 1].includes('</div>')) {
                    i++;
                    parsedLines.push(lines[i]);
                }
                if (i + 1 < lines.length) {
                    i++;
                    parsedLines.push(lines[i]);
                }
                continue;
            }

            const ulMatch = line.match(/^-\s+(.*)/);
            const olMatch = line.match(/^\d+\.\s+(.*)/);
            
            if (ulMatch) {
                if (!inList || listType !== 'ul') {
                    if (inList) parsedLines.push(`</${listType}>`);
                    parsedLines.push('<ul>');
                    inList = true;
                    listType = 'ul';
                }
                parsedLines.push(`<li>${ulMatch[1]}</li>`);
            } else if (olMatch) {
                if (!inList || listType !== 'ol') {
                    if (inList) parsedLines.push(`</${listType}>`);
                    parsedLines.push('<ol>');
                    inList = true;
                    listType = 'ol';
                }
                parsedLines.push(`<li>${olMatch[1]}</li>`);
            } else {
                if (inList) {
                    parsedLines.push(`</${listType}>`);
                    inList = false;
                }
                if (line.trim() !== '' && !line.startsWith('<')) {
                    parsedLines.push(`<p>${line}</p>`);
                } else if (line.trim() === '') {
                    // Empty line means paragraph break if not in a list
                } else {
                    parsedLines.push(line);
                }
            }
        }
        
        if (inList) {
            parsedLines.push(`</${listType}>`);
        }
        
        return parsedLines.join('\n').replace(/<p><\/p>/g, '<br>');
    }

    function setupCopyButtons(container) {
        const buttons = container.querySelectorAll('.copy-btn');
        buttons.forEach(btn => {
            btn.onclick = () => {
                const code = btn.nextElementSibling.textContent;
                navigator.clipboard.writeText(code).then(() => {
                    const originalText = btn.textContent;
                    btn.textContent = 'Copied!';
                    setTimeout(() => {
                        btn.textContent = originalText;
                    }, 2000);
                }).catch(err => {
                    console.error('Failed to copy: ', err);
                });
            };
        });
    }
});
