// 网易云音乐 API 桥接 - 供 Python music_control 调用
// 用法: node ncm_api.js search <keyword>
//       node ncm_api.js url <song_id>

const api = require('../../../tools/node_modules/NeteaseCloudMusicApi');

async function search(keyword) {
    const result = await api.search({ keywords: keyword, type: 1, limit: 5 });
    if (result.body.code !== 200) {
        console.error('搜索失败: code=' + result.body.code);
        process.exit(1);
    }
    const songs = result.body.result.songs || [];
    if (songs.length === 0) {
        console.log(`未找到与「${keyword}」相关的歌曲`);
        return;
    }
    const lines = [`搜索「${keyword}」的结果（前5条）：`];
    songs.slice(0, 5).forEach((s, i) => {
        const artists = s.artists.map(a => a.name).join(', ');
        lines.push(`  ${i + 1}. ${s.name} - ${artists}  [id: ${s.id}]`);
    });
    console.log(lines.join('\n'));
}

async function getUrl(songId) {
    const result = await api.song_url_v1({ id: songId, level: 'standard' });
    if (result.body.code !== 200) {
        console.error('获取URL失败: code=' + result.body.code);
        process.exit(1);
    }
    const data = result.body.data || [];
    if (data.length === 0 || !data[0].url) {
        console.error('无可用音源');
        process.exit(1);
    }
    console.log(JSON.stringify({ url: data[0].url, title: data[0].id }));
}

async function main() {
    const cmd = process.argv[2];
    const arg = process.argv[3];
    if (!cmd || !arg) {
        console.error('用法: node ncm_api.js <search|url> <keyword|song_id>');
        process.exit(1);
    }
    if (cmd === 'search') {
        await search(arg);
    } else if (cmd === 'url') {
        await getUrl(arg);
    } else {
        console.error('未知命令: ' + cmd);
        process.exit(1);
    }
}

main().catch(e => {
    console.error('错误: ' + e.message);
    process.exit(1);
});