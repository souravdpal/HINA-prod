const puppeteer = require('puppeteer');
const fs = require('fs');

const outputFile = process.argv[2] || "stt_output.txt";

(async () => {
    const browser = await puppeteer.launch({
        headless: false,                  // must be visible for mic
        defaultViewport: { width: 10, height: 10 }, // tiny popup
        args: [
            '--use-fake-ui-for-media-stream', // auto-allow mic
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--window-position=2000,2000'     // offscreen if you like
        ]
    });

    const page = await browser.newPage();
    await page.goto('about:blank');

    await page.exposeFunction('saveText', async (text) => {
        fs.writeFileSync(outputFile, text);
        await browser.close();
        process.exit(0);
    });

    await page.evaluate(() => {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.error("Web Speech API not available");
            window.saveText("");
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onresult = (event) => {
            const transcript = Array.from(event.results)
                .map(r => r[0].transcript)
                .join(' ');
            window.saveText(transcript);
        };

        recognition.onerror = (event) => {
            console.error("STT error:", event.error);
            window.saveText("");
        };

        recognition.start();
    });
})();