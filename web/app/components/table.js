/**
 * 
 * ：12.5px、、 hover 、
 */

export function renderTable({ columns = [], data = [], emptyText = 'No items found' } = {}) {
  if (!data || !data.length) {
    return `
      <div class="card" style="padding:var(--sp-8);text-align:center;color:var(--muted);font-size:var(--fs-2);">
        ${emptyText}
      </div>
    `;
  }

  return `
    <div class="tbl card" style="padding:0;overflow:hidden;">
      <table class="table">
        <thead>
          <tr>
            ${columns
              .map(
                (col) => `
              <th style="${col.align ? `text-align:${col.align};` : ''}${col.width ? `width:${col.width};` : ''}">
                ${col.label || ''}
              </th>
            `
              )
              .join('')}
          </tr>
        </thead>
        <tbody>
          ${data
            .map(
              (row, rowIdx) => `
            <tr data-row-idx="${rowIdx}">
              ${columns
                .map((col) => {
                  const val = col.render ? col.render(row, rowIdx) : row[col.key] !== undefined ? row[col.key] : '—';
                  const isNum = col.align === 'right' || col.isNum;
                  return `
                  <td ${isNum ? 'data-num' : ''} style="${col.align ? `text-align:${col.align};` : ''}">
                    ${val}
                  </td>
                `;
                })
                .join('')}
            </tr>
          `
            )
            .join('')}
        </tbody>
      </table>
    </div>
  `;
}

export default { renderTable };
