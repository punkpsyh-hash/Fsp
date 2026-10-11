import { useEffect, useMemo, useState } from "react";

export function usePagedItems<T>(items: T[], pageSize = 10) {
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  const currentPage = Math.min(page, pages);
  const visibleItems = useMemo(
    () => items.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [items, currentPage, pageSize],
  );
  useEffect(() => {
    if (page !== currentPage) setPage(currentPage);
  }, [page, currentPage]);
  return {
    page: currentPage,
    pages,
    pageSize,
    visibleItems,
    setPage,
    start: items.length ? (currentPage - 1) * pageSize + 1 : 0,
    end: Math.min(currentPage * pageSize, items.length),
  };
}

export function Pagination({
  label,
  total,
  page,
  pages,
  start,
  end,
  onPageChange,
  disabled = false,
}: {
  label: string;
  total: number;
  page: number;
  pages: number;
  start: number;
  end: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
}) {
  if (total === 0) return null;
  const windowSize = 5;
  let first = Math.max(1, page - Math.floor(windowSize / 2));
  first = Math.min(first, Math.max(1, pages - windowSize + 1));
  const numbers = Array.from(
    { length: Math.min(windowSize, pages) },
    (_, i) => first + i,
  );
  return (
    <nav className="pagination" aria-label={`Страницы: ${label}`}>
      <p className="pagination-status" role="status" aria-live="polite">
        {label}: {start}–{end} из {total} · страница {page} из {pages}
      </p>
      <div className="pagination-controls">
        <button
          type="button"
          aria-label={`Предыдущая страница списка «${label}»`}
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(Math.max(1, page - 1))}
        >
          Назад
        </button>
        {first > 1 && <span aria-hidden="true">…</span>}
        {numbers.map((number) => (
          <button
            type="button"
            key={number}
            aria-label={`Страница ${number}: ${label}`}
            aria-current={number === page ? "page" : undefined}
            aria-disabled={disabled || number === page || undefined}
            disabled={disabled}
            onClick={() => {
              if (number !== page) onPageChange(number);
            }}
          >
            {number}
          </button>
        ))}
        {first + numbers.length - 1 < pages && (
          <span aria-hidden="true">…</span>
        )}
        <button
          type="button"
          aria-label={`Следующая страница списка «${label}»`}
          disabled={disabled || page >= pages}
          onClick={() => onPageChange(Math.min(pages, page + 1))}
        >
          Далее
        </button>
      </div>
    </nav>
  );
}
