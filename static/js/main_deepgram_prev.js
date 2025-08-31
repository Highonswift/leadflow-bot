// static/js/main.js (Final, Corrected Version for Deepgram)

document.addEventListener('DOMContentLoaded', () => {
    const connectButton = document.getElementById('connect-button');
    const chatMessages = document.getElementById('chat-messages');
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    
    let socket;
    let isConnected = false;
    let isStreaming = false;
    let audioContext;
    let processor;
    let mediaStreamSource;

    let currentUserMessageElement = null;
    let accumulatedFinalTranscript = '';
    let audioChunks = [];

    const setAgentState = (state) => {
        statusIndicator.className = 'status-indicator';
        switch (state) {
            case 'disconnected':
                statusIndicator.classList.add('status-disconnected');
                statusText.textContent = 'Ready';
                connectButton.textContent = 'Connect';
                connectButton.classList.remove('btn-danger');
                connectButton.classList.add('btn-primary');
                break;
            case 'listening':
                statusIndicator.classList.add('status-listening');
                statusText.textContent = 'Listening...';
                break;
            case 'processing':
                statusIndicator.classList.add('status-processing');
                statusText.textContent = 'Thinking...';
                break;
            case 'speaking':
                statusIndicator.classList.add('status-speaking');
                statusText.textContent = 'Speaking...';
                break;
        }
    };

    const addMessageToChat = (sender, text) => {
        const messageElement = document.createElement('div');
        messageElement.classList.add('chat-message', `${sender}-message`);
        const bubble = document.createElement('div');
        bubble.classList.add('message-bubble');
        bubble.textContent = text;
        messageElement.appendChild(bubble);
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return messageElement;
    };

    const createOrUpdateUserMessage = (transcript, isFinal) => {
        if (!currentUserMessageElement) {
            currentUserMessageElement = addMessageToChat('user', '');
        }
        
        let displayText = accumulatedFinalTranscript + transcript;
        currentUserMessageElement.querySelector('.message-bubble').textContent = displayText;

        if (isFinal) {
            accumulatedFinalTranscript += transcript + ' ';
        }
    };

    const playCombinedAudio = () => {
        if (audioChunks.length === 0) {
            if (isConnected) startStreaming();
            return;
        }
        setAgentState('speaking');
        const blob = new Blob(audioChunks, { type: 'audio/mpeg' });
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        
        audio.play();
        audio.onended = () => {
            audioChunks = [];
            URL.revokeObjectURL(audioUrl);
            if (isConnected) {
                startStreaming();
            }
        };
    };

    const startStreaming = async () => {
        if (isStreaming || !isConnected) return;
        accumulatedFinalTranscript = '';
        currentUserMessageElement = null;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            mediaStreamSource = audioContext.createMediaStreamSource(stream);
            processor = audioContext.createScriptProcessor(4096, 1, 1);
            mediaStreamSource.connect(processor);
            processor.connect(audioContext.destination);
            
            processor.onaudioprocess = (e) => {
                if (!isStreaming) return;
                const inputData = e.inputBuffer.getChannelData(0);
                const pcmData = new Int16Array(inputData.length);
                for (let i = 0; i < inputData.length; i++) {
                    let s = Math.max(-1, Math.min(1, inputData[i]));
                    pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                socket.emit('audio_chunk', pcmData.buffer);
            };

            isStreaming = true;
            setAgentState('listening');
            socket.emit('start_stream');
        } catch (error) {
            console.error('Error accessing microphone:', error);
            disconnect();
        }
    };

    const stopStreaming = () => {
        if (!isStreaming) return;
        isStreaming = false;
        
        if (mediaStreamSource && mediaStreamSource.mediaStream) {
            mediaStreamSource.mediaStream.getTracks().forEach(track => track.stop());
        }
        if (processor) processor.disconnect();
        if (mediaStreamSource) mediaStreamSource.disconnect();
        if (audioContext && audioContext.state !== 'closed') audioContext.close();
        
        socket.emit('stop_stream');
        setAgentState('processing');
    };

    const connect = () => {
        socket = io();
        isConnected = true;
        connectButton.textContent = 'Disconnect';
        connectButton.classList.remove('btn-primary');
        connectButton.classList.add('btn-danger');
        socket.on('connect', () => console.log('Socket connected.'));
        socket.on('disconnect', () => disconnect());
        socket.on('agent_response', (data) => {
            // When the agent sends text, we know it's about to speak.
            // We must stop listening to the user.
            if (isStreaming) {
                stopStreaming();
            }
            addMessageToChat('agent', data.text);
        });
        socket.on('transcript_update', (data) => createOrUpdateUserMessage(data.transcript, data.is_final));
        socket.on('audio_chunk', (chunk) => {
            audioChunks.push(chunk);
        });
        socket.on('audio_stream_end', () => playCombinedAudio());
    };

    const disconnect = () => {
        if (isStreaming) stopStreaming();
        if (socket) socket.disconnect();
        isConnected = false;
        setAgentState('disconnected');
    };

    connectButton.addEventListener('click', () => {
        if (isConnected) {
            disconnect();
        } else {
            connect();
        }
    });
});