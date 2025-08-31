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

    // --- NEW: Voice Activity Detection (VAD) variables ---
    let silenceTimer = null;
    let hasStartedSpeaking = false;
    const SILENCE_DURATION = 1500; // 1.5 seconds of silence
    const AMPLITUDE_THRESHOLD = 500; // Adjust this based on your microphone's sensitivity

    let currentUserMessageElement = null;
    let audioChunks = [];

    const setAgentState = (state) => {
        statusIndicator.className = 'status-indicator';
        switch (state) {
            case 'connecting':
                statusText.textContent = 'Connecting...';
                break;
            case 'disconnected':
                statusIndicator.classList.add('status-disconnected');
                statusText.textContent = 'Ready';
                connectButton.textContent = 'Connect';
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
        
        currentUserMessageElement = null;

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

    const createOrUpdateUserMessage = (transcript) => {
        if (!currentUserMessageElement) {
            currentUserMessageElement = addMessageToChat('user', '');
        }
        
        currentUserMessageElement.querySelector('.message-bubble').textContent = transcript;
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
        currentUserMessageElement = null;
        hasStartedSpeaking = false; // Reset VAD flag for the new turn
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            mediaStreamSource = audioContext.createMediaStreamSource(stream);
            processor = audioContext.createScriptProcessor(4096, 1, 1);
            mediaStreamSource.connect(processor);
            processor.connect(audioContext.destination);

            // --- THIS IS THE NEW VAD LOGIC ---
            processor.onaudioprocess = (e) => {
                if (!isStreaming) return;
                
                const inputData = e.inputBuffer.getChannelData(0);

                // Calculate the volume of the audio chunk
                let sum = 0.0;
                for (let i = 0; i < inputData.length; i++) {
                    sum += inputData[i] * inputData[i];
                }
                let rms = Math.sqrt(sum / inputData.length);
                let volume = rms * 10000; // Scale up for easier comparison

                if (volume > AMPLITUDE_THRESHOLD) {
                    // Speech detected
                    hasStartedSpeaking = true;
                    clearTimeout(silenceTimer);
                    silenceTimer = null;
                } else if (hasStartedSpeaking && !silenceTimer) {
                    // Silence detected after speech
                    silenceTimer = setTimeout(() => {
                        console.log("Silence detected, stopping stream.");
                        stopStreaming();
                    }, SILENCE_DURATION);
                }

                const pcmData = new Int16Array(inputData.length);
                for (let i = 0; i < inputData.length; i++) {
                    let s = Math.max(-1, Math.min(1, inputData[i]));
                    pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                socket.emit('audio_chunk', pcmData.buffer);
            };

            isStreaming = true;
            setAgentState('listening');
            // socket.emit('start_stream');
        } catch (error) {
            console.error('Error accessing microphone:', error);
            disconnect();
        }
    };

    const stopStreaming = () => {
        if (!isStreaming) return;
        isStreaming = false;
        
        clearTimeout(silenceTimer); // Clear any pending silence timers
        
        if (mediaStreamSource && mediaStreamSource.mediaStream) {
            mediaStreamSource.mediaStream.getTracks().forEach(track => track.stop());
        }
        if (processor) processor.disconnect();
        if (mediaStreamSource) mediaStreamSource.disconnect();
        if (audioContext && audioContext.state !== 'closed') audioContext.close();
        
        // Only trigger a reply if the user has actually spoken
        if (hasStartedSpeaking) {
            socket.emit('stop_stream');
            setAgentState('processing');
        } else {
            // If the user was silent the whole time, just restart listening
            startStreaming();
        }
    };

    const connect = () => {
        socket = io({
            query: { agent_id: agent_id }
        });
        isConnected = true;
        connectButton.textContent = 'Disconnect';
        connectButton.classList.remove('btn-primary');
        connectButton.classList.add('btn-danger');
        setAgentState('connecting');

        socket.on('connect', () => console.log('Socket connected.'));
        socket.on('disconnect', () => disconnect());
        socket.on('agent_response', (data) => addMessageToChat('agent', data.text));
        socket.on('transcript_update', (data) => createOrUpdateUserMessage(data.transcript));
        socket.on('audio_chunk', (chunk) => {
            if (isStreaming) stopStreaming();
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