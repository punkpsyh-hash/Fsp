import { execFileSync } from 'node:child_process';
import { readFile, writeFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const recording = process.argv.includes('--recording');
const files = [];
for (const name of [recording ? 'demo.mp4' : 'demo-explained.mp4']) {
  const path = '/app/docs/delivery/' + name;
  const data = await readFile(path);
  const metadata = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name,pix_fmt,width,height:format=duration,format_name', '-of', 'json', path], { encoding: 'utf8' }));
  const stream = metadata.streams[0];
  const [width, height] = recording ? [1280, 800] : [1920, 1080];
  if (stream.width !== width || stream.height !== height || Number(metadata.format.duration) < 120) throw new Error('Unexpected video dimensions/duration');
  files.push({ path: 'docs/delivery/' + name, sha256: createHash('sha256').update(data).digest('hex'),
               bytes: (await stat(path)).size, duration_seconds: Number(metadata.format.duration),
               format: name.endsWith('.mp4') ? 'mp4' : 'webm', codec: stream.codec_name,
               pixel_format: stream.pix_fmt, width: stream.width, height: stream.height });
}
if (files[0].codec !== 'h264' || !['yuv420p', 'yuvj420p'].includes(files[0].pixel_format)) throw new Error('Incompatible MP4 encoding');
const videoPath = '/app/' + files[0].path;
const data = await readFile(videoPath);
const atoms = [];
for (let position = 0; position + 8 <= data.length;) {
  const size = data.readUInt32BE(position);
  const type = data.toString('ascii', position + 4, position + 8);
  if (size < 8 || position + size > data.length) throw new Error('Invalid MP4 atom');
  atoms.push({ type, position, size });
  position += size;
}
const moov = atoms.find(atom => atom.type === 'moov'), mdat = atoms.find(atom => atom.type === 'mdat');
if (!moov || !mdat || moov.position >= mdat.position) throw new Error('MP4 is not faststart');
execFileSync('ffmpeg', ['-v', 'error', '-xerror', '-i', videoPath, '-f', 'null', '-'], { stdio: ['ignore', 'pipe', 'pipe'], timeout: 120000 });
await writeFile(process.env.FSP_MEDIA_REPORT || '/app/docs/delivery/media-verification.json', JSON.stringify({
  schema_version: 2, date_utc: new Date().toISOString(), status: 'passed',
  deployment_image: process.env.FSP_DEPLOYMENT_IMAGE || null,
  scope: recording ? 'Проверка формата и декодирования сырой записи.' : 'Проверка формата и декодирования опубликованного видео с пояснениями.',
  files, faststart: { passed: true, moov_position: moov.position, mdat_position: mdat.position },
  checks: [
    { name: 'Совместимый MP4', status: 'passed', evidence: `ffprobe: H.264/${files[0].pixel_format}, ${files[0].width}×${files[0].height}; moov перед mdat` },
    { name: 'Полное декодирование MP4', status: 'passed', evidence: `ffmpeg -v error -xerror -i ${files[0].path} -f null -: exit0, без ошибок` }
  ], generation_command: './scripts/run.sh demo-check',
  limitations: ['Без звука; внешняя интеграция ФСП и почта остаются mock/локальной демонстрацией.', 'Видеозапись не является независимым пилотом или подтверждением качества найма.']
}, null, 2) + '\n');
process.stdout.write(JSON.stringify({ files, faststart: true, full_decode: 'passed' }));
