(function() {
    const scripts = document.getElementsByTagName('script');
    let chatId = null;
    for (let s of scripts) {
        if (s.src.includes('inject.js')) {
            const url = new URL(s.src, window.location.href);
            chatId = url.searchParams.get('id');
            break;
        }
    }
    if (!chatId) return;

    let chatOpen = false;
    let iframe_container = null;

    const button = document.createElement('button');
    button.id = 'floating-chat-button';
    button.innerHTML = '🎙️';
    Object.assign(button.style, {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        width: '60px',
        height: '60px',
        borderRadius: '50%',
        backgroundColor: '#000',
        color: '#fff',
        border: 'none',
        fontSize: '28px',
        cursor: 'pointer',
        zIndex: 9999,
        boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
    });
    document.body.appendChild(button);

    button.addEventListener('click', () => {
        if (!chatOpen) {
            chatOpen = true;
            button.innerHTML = '✖';

            if (iframe_container == null) {
                iframe_container = document.createElement('iframe');
                iframe_container.src = `http://localhost:5000/${chatId}`;
                iframe_container.allow ='microphone';
                Object.assign(iframe_container.style, {
                    position: 'fixed',
                    bottom: '90px',
                    right: '20px',
                    width: '400px',
                    height: '600px',
                    border: 'none',
                    borderRadius: '12px',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
                    zIndex: 9998,
                });
                document.body.appendChild(iframe_container);
            } else {
                iframe_container.style.display = 'block';
                iframe_container.contentWindow.postMessage({ action: 'startListening' }, '*');
            }

        } else {
            chatOpen = false;
            button.innerHTML = '🎙️';
            if (iframe_container) {
                iframe_container.style.display = 'none';
                iframe_container.contentWindow.postMessage({ action: 'stopListening' }, '*');
            }
        }
    });
})();
