import ExcelJS from "exceljs";
import type { TimelineExport } from "../types";

const PROJECT = "daily-news";

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function suggestedFilename(triggeredAt: string): string {
  const d = new Date(triggeredAt);
  const stamp =
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
    `-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  return `${PROJECT}_${stamp}.xlsx`;
}

async function buildWorkbook(data: TimelineExport): Promise<ArrayBuffer> {
  const wb = new ExcelJS.Workbook();
  wb.creator = PROJECT;
  wb.created = new Date();

  const ws = wb.addWorksheet("新增新闻", {
    views: [{ state: "frozen", ySplit: 1 }],
  });

  ws.columns = [
    { header: "新闻时间", key: "pub_date", width: 22 },
    { header: "新闻标题", key: "title", width: 60 },
    { header: "新闻URL", key: "url", width: 80 },
  ];

  const headerRow = ws.getRow(1);
  headerRow.font = { bold: true, color: { argb: "FFFFFFFF" } };
  headerRow.fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: "FF334155" },
  };
  headerRow.alignment = { vertical: "middle" };
  headerRow.height = 22;

  const thinBorder: Partial<ExcelJS.Borders> = {
    top: { style: "thin", color: { argb: "FFE2E8F0" } },
    bottom: { style: "thin", color: { argb: "FFE2E8F0" } },
    left: { style: "thin", color: { argb: "FFE2E8F0" } },
    right: { style: "thin", color: { argb: "FFE2E8F0" } },
  };

  for (const group of data.groups) {
    // 分组标题行:合并三列,显示订阅别名 + 条数
    const aliasRow = ws.addRow([
      `📰 ${group.subscription_alias ?? group.subscription_id} (+${group.items_added} 条)`,
    ]);
    ws.mergeCells(aliasRow.number, 1, aliasRow.number, 3);
    const aliasCell = aliasRow.getCell(1);
    aliasCell.font = { bold: true, size: 12, color: { argb: "FF1E293B" } };
    aliasCell.fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: "FFE0F2FE" },
    };
    aliasCell.alignment = { vertical: "middle", indent: 1 };
    aliasRow.height = 24;
    aliasCell.border = thinBorder;

    for (const item of group.items) {
      const row = ws.addRow({
        pub_date: item.pub_date ?? "—",
        title: item.title,
        url: item.url,
      });
      row.alignment = { vertical: "middle", wrapText: true };
      // URL 做超链接
      const urlCell = row.getCell(3);
      urlCell.value = { text: item.url, hyperlink: item.url };
      urlCell.font = { color: { argb: "FF2563EB" }, underline: true };
      row.eachCell((cell) => {
        cell.border = thinBorder;
      });
    }
  }

  const buf = await wb.xlsx.writeBuffer();
  return buf as ArrayBuffer;
}

declare global {
  interface Window {
    showSaveFilePicker?: (options?: {
      suggestedName?: string;
      types?: { description: string; accept: Record<string, string[]> }[];
    }) => Promise<FileSystemFileHandle>;
  }
}

export async function exportTimelineRun(data: TimelineExport): Promise<void> {
  const buffer = await buildWorkbook(data);
  const filename = suggestedFilename(data.triggered_at);
  const blob = new Blob([buffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

  // 优先用 File System Access API:用户可选保存路径
  if (typeof window.showSaveFilePicker === "function") {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [
          {
            description: "Excel 工作簿",
            accept: {
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                [".xlsx"],
            },
          },
        ],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return;
    } catch (e) {
      // 用户取消(AbortError)直接返回;其他错误降级到 anchor 下载
      if ((e as DOMException).name === "AbortError") return;
    }
  }

  // 降级:浏览器默认下载文件夹
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
