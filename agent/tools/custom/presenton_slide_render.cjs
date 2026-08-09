/**
 * Presenton 幻灯片逐页截图 —— 供视觉排版质检使用
 * 用法: node presenton_slide_render.cjs <pdf_maker_url> <output_dir>
 * 需在 presentation-export 目录下运行（依赖其 node_modules 中的 puppeteer）
 */
const path = require("path");
const fs = require("fs");
const puppeteer = require("puppeteer");

(async () => {
  const [url, outDir] = process.argv.slice(2);
  if (!url || !outDir) {
    console.error("usage: node presenton_slide_render.cjs <url> <output_dir>");
    process.exit(2);
  }
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    headless: true,
    args: ["--no-sandbox", "--font-render-hinting=none"],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900, deviceScaleFactor: 1.5 });
    await page.goto(url, { waitUntil: "networkidle2", timeout: 90000 });
    await page.waitForSelector("#presentation-slides-wrapper .main-slide", {
      timeout: 60000,
    });

    // 等待所有图片与字体加载完成
    await page.evaluate(async () => {
      await Promise.all(
        Array.from(document.images).map((img) =>
          img.complete
            ? null
            : new Promise((resolve) => {
                img.onload = img.onerror = resolve;
              })
        )
      );
      if (document.fonts && document.fonts.ready) {
        await document.fonts.ready;
      }
    });
    await new Promise((r) => setTimeout(r, 1500));

    const slides = await page.$$("#presentation-slides-wrapper .main-slide");
    const files = [];
    for (let i = 0; i < slides.length; i++) {
      const file = path.join(outDir, `slide_${String(i + 1).padStart(2, "0")}.png`);
      await slides[i].screenshot({ path: file });
      files.push(file);
    }
    console.log(JSON.stringify({ count: files.length, files }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error("[render] " + (e && e.message ? e.message : e));
  process.exit(1);
});
