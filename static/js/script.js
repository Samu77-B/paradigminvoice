let previewInvoiceId = null;
let previewQuoteId = null;
let allInvoices = [];
let invoicePaidFilter = 'unpaid';
let activeSection = 'invoices';
let summaryPeriod = 'month';

document.addEventListener('DOMContentLoaded', () => {
  loadClients();
  loadInvoices();
  loadQuotes();
  addInvoiceItem();

  const vatCb = document.getElementById('invoiceVatApplies');
  if (vatCb) {
    vatCb.addEventListener('change', syncInvoiceVatUi);
  }
  const editVatCb = document.getElementById('editInvoiceVatApplies');
  if (editVatCb) {
    editVatCb.addEventListener('change', syncEditInvoiceVatUi);
  }
  const quoteVatCb = document.getElementById('quoteVatApplies');
  if (quoteVatCb) {
    quoteVatCb.addEventListener('change', syncQuoteVatUi);
  }
  const editQuoteVatCb = document.getElementById('editQuoteVatApplies');
  if (editQuoteVatCb) {
    editQuoteVatCb.addEventListener('change', syncEditQuoteVatUi);
  }

  const newInvModal = document.getElementById('newInvoiceModal');
  if (newInvModal) {
    newInvModal.addEventListener('shown.bs.modal', () => {
      const box = document.getElementById('invoiceItems');
      if (box && box.children.length === 0) {
        addInvoiceItem();
      }
      const vatCheck = document.getElementById('invoiceVatApplies');
      const vatRate = document.getElementById('invoiceVatRate');
      if (vatCheck) vatCheck.checked = false;
      if (vatRate) vatRate.value = '20';
      syncInvoiceVatUi();
      const invNum = document.getElementById('invoiceNumber');
      if (invNum) invNum.value = '';
      updateSuggestedInvoiceNumber();
    });
  }

  const invoiceClientSelect = document.getElementById('invoiceClient');
  if (invoiceClientSelect) {
    invoiceClientSelect.addEventListener('change', updateSuggestedInvoiceNumber);
  }

  const newQuoteModal = document.getElementById('newQuoteModal');
  if (newQuoteModal) {
    newQuoteModal.addEventListener('shown.bs.modal', () => {
      const box = document.getElementById('quoteItems');
      if (box && box.children.length === 0) {
        addQuoteItem();
      }
      const vatCheck = document.getElementById('quoteVatApplies');
      const vatRate = document.getElementById('quoteVatRate');
      if (vatCheck) vatCheck.checked = false;
      if (vatRate) vatRate.value = '20';
      syncQuoteVatUi();
    });
  }

  const reportsModal = document.getElementById('reportsModal');
  if (reportsModal) {
    reportsModal.addEventListener('shown.bs.modal', () => {
      loadReport('month');
    });
  }
});

function escapeHtml(text) {
  if (text == null) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

function removeLineItemRow(btn) {
  const row = btn.closest('.line-item-row');
  const container = row?.parentElement;
  if (!row || !container) return;
  if (container.querySelectorAll('.line-item-row').length <= 1) {
    showError('At least one line item is required');
    return;
  }
  row.remove();
}

function collectLineItems(containerId) {
  const container = document.getElementById(containerId);
  if (!container) {
    return { error: 'Line items not found' };
  }

  const descriptions = Array.from(container.querySelectorAll('input[name="description[]"]')).map(
    (input) => input.value.trim()
  );
  const amounts = Array.from(container.querySelectorAll('input[name="amount[]"]')).map((input) =>
    parseFloat(input.value)
  );

  if (descriptions.length === 0) {
    return { error: 'Please add at least one line item' };
  }

  for (let i = 0; i < descriptions.length; i += 1) {
    if (!descriptions[i]) {
      return { error: 'Each line item needs a description' };
    }
    if (Number.isNaN(amounts[i])) {
      return { error: 'Please enter a valid amount for each line' };
    }
  }

  return {
    items: descriptions.map((description, index) => ({
      description,
      amount: amounts[index],
    })),
  };
}

function formatUkDate(isoYmd) {
  if (!isoYmd) return '';
  const p = isoYmd.split('-');
  if (p.length !== 3) return isoYmd;
  return `${p[2]}/${p[1]}/${p[0]}`;
}

async function apiFetch(url, options = {}) {
  const r = await fetch(url, { credentials: 'same-origin', ...options });
  if (r.status === 401) {
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  return r;
}

function syncInvoiceVatUi() {
  const cb = document.getElementById('invoiceVatApplies');
  const wrap = document.getElementById('invoiceVatRateWrap');
  if (cb && wrap) wrap.style.display = cb.checked ? 'block' : 'none';
}

function syncEditInvoiceVatUi() {
  const cb = document.getElementById('editInvoiceVatApplies');
  const wrap = document.getElementById('editInvoiceVatRateWrap');
  if (cb && wrap) wrap.style.display = cb.checked ? 'block' : 'none';
}

function syncQuoteVatUi() {
  const cb = document.getElementById('quoteVatApplies');
  const wrap = document.getElementById('quoteVatRateWrap');
  if (cb && wrap) wrap.style.display = cb.checked ? 'block' : 'none';
}

function syncEditQuoteVatUi() {
  const cb = document.getElementById('editQuoteVatApplies');
  const wrap = document.getElementById('editQuoteVatRateWrap');
  if (cb && wrap) wrap.style.display = cb.checked ? 'block' : 'none';
}

function switchSection(section) {
  activeSection = section;
  const invoicesSection = document.getElementById('invoicesSection');
  const quotesSection = document.getElementById('quotesSection');
  const tabInvoices = document.getElementById('tabInvoices');
  const tabQuotes = document.getElementById('tabQuotes');
  const btnNewInvoice = document.getElementById('btnNewInvoice');
  const btnNewQuote = document.getElementById('btnNewQuote');

  const isInvoices = section === 'invoices';
  if (invoicesSection) invoicesSection.classList.toggle('d-none', !isInvoices);
  if (quotesSection) quotesSection.classList.toggle('d-none', isInvoices);
  if (tabInvoices) {
    tabInvoices.classList.toggle('is-active', isInvoices);
    tabInvoices.setAttribute('aria-selected', isInvoices ? 'true' : 'false');
  }
  if (tabQuotes) {
    tabQuotes.classList.toggle('is-active', !isInvoices);
    tabQuotes.setAttribute('aria-selected', !isInvoices ? 'true' : 'false');
  }
  if (btnNewInvoice) btnNewInvoice.classList.toggle('d-none', !isInvoices);
  if (btnNewQuote) btnNewQuote.classList.toggle('d-none', isInvoices);
  renderSummaryBar();
}

function switchSummaryPeriod(period) {
  summaryPeriod = period;
  setSummaryPeriodUI(period);
  loadSummary();
}

function setSummaryPeriodUI(period) {
  const buttons = {
    week: document.getElementById('summaryWeekBtn'),
    month: document.getElementById('summaryMonthBtn'),
    year: document.getElementById('summaryYearBtn'),
  };
  Object.entries(buttons).forEach(([key, btn]) => {
    if (!btn) return;
    const active = key === period;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
}

let summaryData = null;

async function loadSummary() {
  const statsEl = document.getElementById('summaryStats');
  const rangeEl = document.getElementById('summaryRange');
  if (!statsEl) return;
  statsEl.innerHTML = '<p class="text-muted mb-0">Loading totals…</p>';
  try {
    const response = await apiFetch(`/api/summary?period=${encodeURIComponent(summaryPeriod)}`);
    if (!response.ok) throw new Error('Failed to load summary');
    summaryData = await response.json();
    if (rangeEl) {
      rangeEl.textContent = `${formatUkDate(summaryData.range_start)} – ${formatUkDate(summaryData.range_end)} · UTC calendar ${summaryData.period}`;
    }
    renderSummaryBar();
  } catch (error) {
    statsEl.innerHTML = `<p class="text-danger mb-0">${escapeHtml(error.message || 'Failed to load summary')}</p>`;
  }
}

function renderSummaryBar() {
  const statsEl = document.getElementById('summaryStats');
  if (!statsEl || !summaryData) return;

  if (activeSection === 'quotes') {
    statsEl.innerHTML = `
      <div class="summary-stat is-owed">
        <p class="label">Outstanding quotes</p>
        <p class="value">£${Number(summaryData.quotes.owed_total).toFixed(2)}</p>
      </div>
      <div class="summary-stat is-paid">
        <p class="label">Paid (via invoice)</p>
        <p class="value">£${Number(summaryData.quotes.paid_total).toFixed(2)}</p>
      </div>
      <div class="summary-stat">
        <p class="label">Quotes in period</p>
        <p class="value">${summaryData.quotes.count}</p>
      </div>`;
    return;
  }

  statsEl.innerHTML = `
    <div class="summary-stat is-owed">
      <p class="label">Money owed</p>
      <p class="value">£${Number(summaryData.invoices.owed_total).toFixed(2)}</p>
    </div>
    <div class="summary-stat is-paid">
      <p class="label">Money paid</p>
      <p class="value">£${Number(summaryData.invoices.paid_total).toFixed(2)}</p>
    </div>
    <div class="summary-stat">
      <p class="label">Invoices in period</p>
      <p class="value">${summaryData.invoices.count}</p>
    </div>`;
}

function refreshSummary() {
  loadSummary();
}

function switchInvoiceFilter(filter) {
  invoicePaidFilter = filter;
  const filterUnpaid = document.getElementById('filterUnpaid');
  const filterPaid = document.getElementById('filterPaid');
  const heading = document.getElementById('invoicesHeading');

  if (filterUnpaid) {
    filterUnpaid.classList.toggle('is-active', filter === 'unpaid');
    filterUnpaid.setAttribute('aria-selected', filter === 'unpaid' ? 'true' : 'false');
  }
  if (filterPaid) {
    filterPaid.classList.toggle('is-active', filter === 'paid');
    filterPaid.setAttribute('aria-selected', filter === 'paid' ? 'true' : 'false');
  }
  if (heading) {
    heading.textContent = filter === 'paid' ? 'Paid invoices' : 'Unpaid invoices';
  }
  renderInvoicesList();
}

function setReportPeriodUI(period) {
  const w = document.getElementById('reportWeekBtn');
  const m = document.getElementById('reportMonthBtn');
  const y = document.getElementById('reportYearBtn');
  if (!w || !m || !y) return;
  w.classList.toggle('btn-apple-primary', period === 'week');
  w.classList.toggle('btn-apple-secondary', period !== 'week');
  m.classList.toggle('btn-apple-primary', period === 'month');
  m.classList.toggle('btn-apple-secondary', period !== 'month');
  y.classList.toggle('btn-apple-primary', period === 'year');
  y.classList.toggle('btn-apple-secondary', period !== 'year');
}

async function loadReport(period) {
  setReportPeriodUI(period);
  const el = document.getElementById('reportsContent');
  if (!el) return;
  el.innerHTML = '<p class="text-muted mb-0">Loading…</p>';
  try {
    const response = await apiFetch(`/api/reports?period=${encodeURIComponent(period)}`);
    if (!response.ok) throw new Error('Failed to load report');
    const data = await response.json();
    const rowsHtml = (data.invoices || [])
      .map(
        (inv) => `
      <tr>
        <td>${escapeHtml(inv.invoice_number)}</td>
        <td>${escapeHtml(formatUkDate(inv.date))}</td>
        <td>${escapeHtml(inv.client_name)}</td>
        <td class="text-end">£${Number(inv.total_amount).toFixed(2)}</td>
        <td>${inv.paid ? '<span class="text-success">Paid</span>' : '<span class="text-warning">Unpaid</span>'}</td>
      </tr>`
      )
      .join('');
    el.innerHTML = `
      <p class="text-muted mb-3" style="font-size: 13px;">${escapeHtml(data.range_start)} – ${escapeHtml(data.range_end)} · UTC calendar ${escapeHtml(data.period)}</p>
      <h6 class="mb-2">Invoices</h6>
      <div class="reports-summary">
        <div class="reports-stat"><p class="label">Invoices</p><p class="value">${data.invoice_count}</p></div>
        <div class="reports-stat"><p class="label">Owed</p><p class="value">£${Number(data.unpaid_total).toFixed(2)}</p></div>
        <div class="reports-stat"><p class="label">Paid</p><p class="value">£${Number(data.paid_total).toFixed(2)}</p></div>
        <div class="reports-stat"><p class="label">Total invoiced</p><p class="value">£${Number(data.total_invoiced).toFixed(2)}</p></div>
      </div>
      <h6 class="mb-2 mt-3">Quotes</h6>
      <div class="reports-summary">
        <div class="reports-stat"><p class="label">Quotes</p><p class="value">${data.quote_count ?? 0}</p></div>
        <div class="reports-stat"><p class="label">Outstanding</p><p class="value">£${Number(data.quote_owed_total ?? 0).toFixed(2)}</p></div>
        <div class="reports-stat"><p class="label">Paid (via invoice)</p><p class="value">£${Number(data.quote_paid_total ?? 0).toFixed(2)}</p></div>
      </div>
      <div class="table-responsive rounded-3 border mt-3" style="border-color: var(--border) !important;">
        <table class="table table-dark table-striped mb-0" style="--bs-table-bg: transparent;">
          <thead><tr><th>Invoice</th><th>Date</th><th>Client</th><th class="text-end">Total</th><th>Status</th></tr></thead>
          <tbody>${rowsHtml || '<tr><td colspan="5" class="text-muted">No invoices in this period.</td></tr>'}</tbody>
        </table>
      </div>`;
  } catch (e) {
    el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(e.message || 'Failed to load report')}</p>`;
  }
}

async function loadClients() {
  try {
    const response = await apiFetch('/api/clients');
    if (!response.ok) throw new Error('Failed to load clients');
    const clients = await response.json();

    const selects = [
      document.querySelector('#invoiceForm select[name="client_id"]'),
      document.getElementById('quoteClient'),
    ].filter(Boolean);

    selects.forEach((clientSelect) => {
      clientSelect.innerHTML = '<option value="">Select a client…</option>';
      clients.forEach((client) => {
        const option = document.createElement('option');
        option.value = client.id;
        option.textContent = client.name;
        clientSelect.appendChild(option);
      });
    });
  } catch (error) {
    showError('Failed to load clients: ' + error.message);
  }
}

async function updateSuggestedInvoiceNumber() {
  const select = document.getElementById('invoiceClient');
  const hint = document.getElementById('invoiceNumberHint');
  const input = document.getElementById('invoiceNumber');
  const clientId = select?.value;

  if (!clientId) {
    if (hint) {
      hint.textContent = 'Pick a client to see the next number, or enter your own (e.g. TOX200).';
    }
    return;
  }

  try {
    const response = await apiFetch(`/api/clients/${clientId}/next-invoice-number`);
    if (!response.ok) throw new Error('Failed to load next invoice number');
    const data = await response.json();
    if (hint) {
      hint.textContent = `Next auto number: ${data.invoice_number}. Leave the field blank to use it, or enter a different starting code.`;
    }
    if (input && !input.value.trim()) {
      input.placeholder = data.invoice_number;
    }
  } catch (error) {
    if (hint) hint.textContent = 'Enter an invoice number or leave blank to auto-generate.';
  }
}

async function saveClient() {
  try {
    const form = document.getElementById('clientForm');
    const name = form.querySelector('[name="name"]').value.trim();
    const email = form.querySelector('[name="email"]').value.trim();
    const address = (form.querySelector('[name="address"]')?.value || '').trim();

    if (!name || !email) {
      showError('Name and email are required');
      return;
    }

    const response = await apiFetch('/api/clients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, address }),
    });

    if (!response.ok) throw new Error('Failed to save client');

    showSuccess('Client saved successfully');
    form.reset();
    bootstrap.Modal.getInstance(document.getElementById('newClientModal')).hide();
    loadClients();
  } catch (error) {
    showError('Failed to save client: ' + error.message);
  }
}

function addInvoiceItem() {
  const container = document.getElementById('invoiceItems');
  const newItem = document.createElement('div');
  newItem.className = 'line-item-row';
  newItem.innerHTML = `
        <div class="line-item-desc">
          <input type="text" class="form-control" name="description[]" placeholder="Description" required>
        </div>
        <div class="line-item-amt">
          <input type="number" step="0.01" class="form-control" name="amount[]" placeholder="0.00" required>
        </div>
        <div class="line-item-rm">
          <button type="button" class="btn-remove-line" aria-label="Remove line" onclick="removeLineItemRow(this)">×</button>
        </div>
    `;
  container.appendChild(newItem);
}

async function saveInvoice() {
  try {
    const form = document.getElementById('invoiceForm');
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }

    const clientId = form.querySelector('select[name="client_id"]').value;
    if (!clientId) {
      showError('Please select a client');
      return;
    }

    const descriptions = Array.from(form.querySelectorAll('input[name="description[]"]')).map((input) => input.value);
    const amounts = Array.from(form.querySelectorAll('input[name="amount[]"]')).map((input) => parseFloat(input.value));

    if (descriptions.length === 0) {
      showError('Please add at least one invoice item');
      return;
    }

    const items = descriptions.map((description, index) => ({
      description,
      amount: amounts[index],
    }));

    const vatApplies = document.getElementById('invoiceVatApplies')?.checked || false;
    const vatRateRaw = document.getElementById('invoiceVatRate')?.value;
    const vatRatePercent = vatApplies ? parseFloat(vatRateRaw) : undefined;
    if (vatApplies && (Number.isNaN(vatRatePercent) || vatRatePercent < 0 || vatRatePercent > 100)) {
      showError('Enter a valid VAT rate between 0 and 100');
      return;
    }

    const invoiceNumber = (document.getElementById('invoiceNumber')?.value || '').trim();
    const payload = {
      client_id: parseInt(clientId, 10),
      items,
      vat_applies: vatApplies,
      vat_rate_percent: vatRatePercent,
    };
    if (invoiceNumber) {
      payload.invoice_number = invoiceNumber;
    }

    const response = await apiFetch('/api/invoices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to save invoice');
    }

    const result = await response.json();
    showSuccess(`Invoice ${result.invoice_number} created successfully for ${result.client_name}`);
    form.reset();
    document.getElementById('invoiceItems').innerHTML = '';
    addInvoiceItem();
    bootstrap.Modal.getInstance(document.getElementById('newInvoiceModal')).hide();
    loadInvoices();
  } catch (error) {
    showError('Failed to save invoice: ' + error.message);
  }
}

function renderInvoicePreviewHtml(invoice) {
  const addr = (invoice.client.address || '').trim();
  const billToLines = [escapeHtml(invoice.client.name)];
  if (addr) billToLines.push(escapeHtml(addr).replace(/\n/g, '<br>'));
  billToLines.push(`<span class="text-muted">${escapeHtml(invoice.client.email)}</span>`);

  const rows = invoice.items
    .map(
      (item) => `
                    <tr>
                        <td>${escapeHtml(item.description)}</td>
                        <td class="text-end">£${Number(item.amount).toFixed(2)}</td>
                    </tr>`
    )
    .join('');

  const subtotal =
    invoice.subtotal_net != null
      ? Number(invoice.subtotal_net)
      : invoice.items.reduce((s, item) => s + Number(item.amount), 0);
  const vatApplies = !!invoice.vat_applies;
  const amtHeading = vatApplies ? 'Amount (net)' : 'Amount';
  const vatRows = vatApplies
    ? `
                <tr>
                    <td class="text-end" style="border-left: none; border-bottom: none;">Subtotal (net)</td>
                    <td class="text-end">£${subtotal.toFixed(2)}</td>
                </tr>
                <tr>
                    <td class="text-end" style="border-left: none; border-bottom: none;">VAT (${Number(
                      invoice.vat_rate_percent ?? 20
                    ).toFixed(2)}%)</td>
                    <td class="text-end">£${Number(invoice.vat_amount || 0).toFixed(2)}</td>
                </tr>`
    : '';
  const totalLabel = vatApplies ? 'Total due' : 'Total';

  return `
        <div class="invoice-header">
            <div class="invoice-header-left">
                <img src="/static/logo.png" alt="" class="invoice-logo" width="56" height="56">
                <div class="invoice-from">
                    <h2>Paul Banning</h2>
                    <p>48 Pellipar Close<br>
                    London N13 4AG<br>
                    07730 556097</p>
                </div>
            </div>
            <div class="text-end">
                <h1>INVOICE</h1>
                <p>Invoice #: ${escapeHtml(invoice.invoice_number)}<br>
                Date: ${escapeHtml(formatUkDate(invoice.date))}</p>
            </div>
        </div>

        <div class="invoice-details">
            <h4>Bill To</h4>
            <p>${billToLines.join('<br>')}</p>
        </div>

        <table class="invoice-items">
            <thead>
                <tr>
                    <th style="width: 70%">Description</th>
                    <th style="width: 30%" class="text-end">${amtHeading}</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
                ${vatRows}
                <tr>
                    <td class="text-end" style="border-left: none; border-bottom: none;"><strong>${totalLabel}</strong></td>
                    <td class="text-end"><strong>£${Number(invoice.total_amount).toFixed(2)}</strong></td>
                </tr>
            </tbody>
        </table>

        <div class="invoice-terms">
            <h5>Terms &amp; Conditions</h5>
            <p>Payment is due on receipt of invoice</p>

            <h5>Bank details</h5>
            <p>Paul Banning<br>
            Account 72113763<br>
            Sort code 60-83-71</p>
        </div>
    `;
}

async function openInvoicePreview(invoiceId) {
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}`);
    if (!response.ok) throw new Error('Failed to load invoice');
    const invoice = await response.json();
    previewInvoiceId = invoice.id;

    const msg = document.getElementById('emailMessage');
    if (msg) msg.value = '';

    const preview = document.getElementById('invoicePreview');
    preview.className = 'invoice-preview';
    preview.innerHTML = renderInvoicePreviewHtml(invoice);

    const modal = new bootstrap.Modal(document.getElementById('invoicePreviewModal'));
    modal.show();
  } catch (error) {
    showError('Failed to open preview: ' + error.message);
  }
}

async function openEditInvoice(invoiceId) {
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}`);
    if (!response.ok) throw new Error('Failed to load invoice');
    const invoice = await response.json();

    const form = document.getElementById('editInvoiceForm');
    form.querySelector('input[name="invoice_id"]').value = invoice.id;
    form.querySelector('input[name="invoice_number"]').value = invoice.invoice_number;
    form.querySelector('input[name="client_name"]').value = invoice.client.name;

    const itemsContainer = document.getElementById('editInvoiceItems');
    itemsContainer.innerHTML = `
            <div class="row mb-2">
                <div class="col-8">
                    <label class="form-label">Description</label>
                </div>
                <div class="col-4">
                    <label class="form-label">Amount (£)</label>
                </div>
            </div>
        `;

    invoice.items.forEach((item) => addEditInvoiceItem(item));

    const ev = document.getElementById('editInvoiceVatApplies');
    const er = document.getElementById('editInvoiceVatRate');
    if (ev) ev.checked = !!invoice.vat_applies;
    if (er) {
      er.value =
        invoice.vat_applies && invoice.vat_rate_percent != null
          ? String(invoice.vat_rate_percent)
          : '20';
    }
    syncEditInvoiceVatUi();

    const modal = new bootstrap.Modal(document.getElementById('editInvoiceModal'));
    modal.show();
  } catch (error) {
    showError('Failed to edit invoice: ' + error.message);
  }
}

function addEditInvoiceItem(item = null) {
  const container = document.getElementById('editInvoiceItems');
  const newItem = document.createElement('div');
  newItem.className = 'line-item-row';
  newItem.innerHTML = `
        <div class="line-item-desc">
          <input type="text" class="form-control" name="description[]" placeholder="Description" required>
        </div>
        <div class="line-item-amt">
          <input type="number" step="0.01" class="form-control" name="amount[]" placeholder="0.00" required>
        </div>
        <div class="line-item-rm">
          <button type="button" class="btn-remove-line" aria-label="Remove line" onclick="removeLineItemRow(this)">×</button>
        </div>
    `;
  const descInput = newItem.querySelector('input[name="description[]"]');
  const amtInput = newItem.querySelector('input[name="amount[]"]');
  if (item) {
    descInput.value = item.description;
    amtInput.value = item.amount;
  }
  container.appendChild(newItem);
}

async function updateInvoice() {
  try {
    const form = document.getElementById('editInvoiceForm');
    const invoiceId = form.querySelector('input[name="invoice_id"]').value;
    const invoiceNumber = (form.querySelector('input[name="invoice_number"]').value || '').trim();
    const lineItems = collectLineItems('editInvoiceItems');
    if (lineItems.error) {
      showError(lineItems.error);
      return;
    }

    const vatApplies = document.getElementById('editInvoiceVatApplies')?.checked || false;
    const vatRateRaw = document.getElementById('editInvoiceVatRate')?.value;
    const vatRatePercent = vatApplies ? parseFloat(vatRateRaw) : undefined;
    if (vatApplies && (Number.isNaN(vatRatePercent) || vatRatePercent < 0 || vatRatePercent > 100)) {
      showError('Enter a valid VAT rate between 0 and 100');
      return;
    }

    const response = await apiFetch(`/api/invoices/${invoiceId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: lineItems.items,
        invoice_number: invoiceNumber,
        vat_applies: vatApplies,
        vat_rate_percent: vatRatePercent,
      }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to update invoice');
    }

    showSuccess('Invoice updated successfully');
    bootstrap.Modal.getInstance(document.getElementById('editInvoiceModal')).hide();
    loadInvoices();
  } catch (error) {
    showError(error.message || 'Failed to update invoice');
  }
}

async function deleteInvoice(invoiceId) {
  if (!confirm('Are you sure you want to delete this invoice?')) return;

  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}`, {
      method: 'DELETE',
    });

    if (!response.ok) throw new Error('Failed to delete invoice');

    showSuccess('Invoice deleted successfully');
    loadInvoices();
  } catch (error) {
    showError('Failed to delete invoice: ' + error.message);
  }
}

async function duplicateInvoice(invoiceId) {
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}/duplicate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Failed to duplicate invoice');
    }
    showSuccess(`Duplicated as ${data.invoice_number}`);
    await loadInvoices();
    if (data.id) {
      openEditInvoice(data.id);
    }
  } catch (error) {
    showError(error.message || 'Failed to duplicate invoice');
  }
}

async function loadInvoices() {
  try {
    const response = await apiFetch('/api/invoices');
    if (!response.ok) throw new Error('Failed to load invoices');
    allInvoices = await response.json();
    renderInvoicesList();
  } catch (error) {
    showError('Failed to load invoices: ' + error.message);
  } finally {
    loadSummary();
  }
}

function renderInvoicesList() {
  const list = document.getElementById('invoicesList');
  if (!list) return;
  list.innerHTML = '';

  const invoices = allInvoices.filter((invoice) =>
    invoicePaidFilter === 'paid' ? invoice.paid : !invoice.paid
  );

  if (invoices.length === 0) {
    const label = invoicePaidFilter === 'paid' ? 'paid' : 'unpaid';
    list.innerHTML = `<div class="empty-state">No ${label} invoices yet.</div>`;
    return;
  }

  invoices.forEach((invoice) => {
    const item = document.createElement('div');
    item.className = 'invoice-card';
    item.innerHTML = `
                <div class="invoice-card-main">
                    <p class="invoice-card-title">${escapeHtml(invoice.invoice_number)} — ${escapeHtml(invoice.client.name)}</p>
                    <p class="invoice-card-meta">Date: ${escapeHtml(formatUkDate(invoice.date))}</p>
                    ${
                      invoice.vat_applies
                        ? `<p class="invoice-card-vat">VAT ${Number(invoice.vat_rate_percent ?? 20).toFixed(2)}% · Net £${Number(
                            invoice.subtotal_net ?? 0
                          ).toFixed(2)}</p>`
                        : ''
                    }
                    <p class="invoice-card-amount">£${Number(invoice.total_amount).toFixed(2)}</p>
                </div>
                <div class="invoice-card-actions">
                    <button type="button" class="btn-apple-icon" title="Preview" aria-label="Preview" onclick="openInvoicePreview(${invoice.id})">
                        <i class="fas fa-eye"></i>
                    </button>
                    <button type="button" class="btn-apple-icon" title="Edit" aria-label="Edit" onclick="openEditInvoice(${invoice.id})">
                        <i class="fas fa-pen"></i>
                    </button>
                    <button type="button" class="btn-apple-icon" title="Duplicate" aria-label="Duplicate" onclick="duplicateInvoice(${invoice.id})">
                        <i class="fas fa-copy"></i>
                    </button>
                    <button type="button" class="btn-apple-icon ${invoice.paid ? 'is-paid' : 'is-unpaid'}" title="Toggle paid" aria-label="Toggle paid"
                            onclick="togglePaidStatus(${invoice.id}, ${!invoice.paid})">
                        <i class="fas fa-${invoice.paid ? 'check' : 'clock'}"></i>
                    </button>
                    <button type="button" class="btn-apple-icon is-danger" title="Delete" aria-label="Delete" onclick="deleteInvoice(${invoice.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
    list.appendChild(item);
  });
}

async function togglePaidStatus(invoiceId, isPaid) {
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}/paid`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paid: isPaid }),
    });

    if (!response.ok) throw new Error('Failed to update payment status');

    showSuccess(`Invoice marked as ${isPaid ? 'paid' : 'unpaid'}`);
    loadInvoices();
  } catch (error) {
    showError('Failed to update payment status: ' + error.message);
  }
}

async function sendInvoiceEmail() {
  if (!previewInvoiceId) {
    showError('Open an invoice preview first');
    return;
  }
  const btn = document.getElementById('btnSendInvoice');
  if (btn) {
    btn.disabled = true;
  }
  try {
    const msgEl = document.getElementById('emailMessage');
    const message = (msgEl?.value || '').trim();
    const response = await apiFetch(`/api/invoices/${previewInvoiceId}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Send failed');
    }
    showSuccess('Invoice sent to client email');
  } catch (error) {
    showError(error.message || 'Failed to send email');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function printInvoice() {
  const el = document.querySelector('#invoicePreviewModal .invoice-preview');
  if (!el) return;

  const invoiceContent = el.cloneNode(true);
  const printContainer = document.createElement('div');
  printContainer.className = 'print-container';
  printContainer.style.cssText = `
        position: fixed;
        left: 0;
        top: 0;
        width: 100%;
        max-width: 210mm;
        height: auto;
        min-height: 0;
        padding: 0;
        margin: 0;
        background-color: white;
        z-index: 9999;
        overflow: visible;
    `;

  printContainer.appendChild(invoiceContent);
  document.body.appendChild(printContainer);

  setTimeout(() => {
    window.print();
    document.body.removeChild(printContainer);
  }, 200);
}

function savePDF() {
  printInvoice();
}

function addQuoteItem() {
  const container = document.getElementById('quoteItems');
  const newItem = document.createElement('div');
  newItem.className = 'line-item-row';
  newItem.innerHTML = `
        <div class="line-item-desc">
          <input type="text" class="form-control" name="description[]" placeholder="Description" required>
        </div>
        <div class="line-item-amt">
          <input type="number" step="0.01" class="form-control" name="amount[]" placeholder="0.00" required>
        </div>
        <div class="line-item-rm">
          <button type="button" class="btn-remove-line" aria-label="Remove line" onclick="removeLineItemRow(this)">×</button>
        </div>
    `;
  container.appendChild(newItem);
}

async function saveQuote() {
  try {
    const form = document.getElementById('quoteForm');
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }

    const clientId = form.querySelector('select[name="client_id"]').value;
    if (!clientId) {
      showError('Please select a client');
      return;
    }

    const descriptions = Array.from(form.querySelectorAll('#quoteItems input[name="description[]"]')).map((input) => input.value);
    const amounts = Array.from(form.querySelectorAll('#quoteItems input[name="amount[]"]')).map((input) => parseFloat(input.value));

    if (descriptions.length === 0) {
      showError('Please add at least one line item');
      return;
    }

    const items = descriptions.map((description, index) => ({
      description,
      amount: amounts[index],
    }));

    const vatApplies = document.getElementById('quoteVatApplies')?.checked || false;
    const vatRateRaw = document.getElementById('quoteVatRate')?.value;
    const vatRatePercent = vatApplies ? parseFloat(vatRateRaw) : undefined;
    if (vatApplies && (Number.isNaN(vatRatePercent) || vatRatePercent < 0 || vatRatePercent > 100)) {
      showError('Enter a valid VAT rate between 0 and 100');
      return;
    }

    const response = await apiFetch('/api/quotes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: parseInt(clientId, 10),
        items,
        vat_applies: vatApplies,
        vat_rate_percent: vatRatePercent,
      }),
    });

    if (!response.ok) throw new Error('Failed to save quote');

    const result = await response.json();
    showSuccess(`Quote ${result.quote_number} created successfully for ${result.client_name}`);
    form.reset();
    document.getElementById('quoteItems').innerHTML = '';
    addQuoteItem();
    bootstrap.Modal.getInstance(document.getElementById('newQuoteModal')).hide();
    switchSection('quotes');
    loadQuotes();
  } catch (error) {
    showError('Failed to save quote: ' + error.message);
  }
}

function renderQuotePreviewHtml(quote) {
  const addr = (quote.client.address || '').trim();
  const billToLines = [escapeHtml(quote.client.name)];
  if (addr) billToLines.push(escapeHtml(addr).replace(/\n/g, '<br>'));
  billToLines.push(`<span class="text-muted">${escapeHtml(quote.client.email)}</span>`);

  const rows = quote.items
    .map(
      (item) => `
                    <tr>
                        <td>${escapeHtml(item.description)}</td>
                        <td class="text-end">£${Number(item.amount).toFixed(2)}</td>
                    </tr>`
    )
    .join('');

  const subtotal =
    quote.subtotal_net != null
      ? Number(quote.subtotal_net)
      : quote.items.reduce((s, item) => s + Number(item.amount), 0);
  const vatApplies = !!quote.vat_applies;
  const amtHeading = vatApplies ? 'Amount (net)' : 'Amount';
  const vatRows = vatApplies
    ? `
                <tr>
                    <td class="text-end" style="border-left: none; border-bottom: none;">Subtotal (net)</td>
                    <td class="text-end">£${subtotal.toFixed(2)}</td>
                </tr>
                <tr>
                    <td class="text-end" style="border-left: none; border-bottom: none;">VAT (${Number(
                      quote.vat_rate_percent ?? 20
                    ).toFixed(2)}%)</td>
                    <td class="text-end">£${Number(quote.vat_amount || 0).toFixed(2)}</td>
                </tr>`
    : '';
  const totalLabel = vatApplies ? 'Total quoted' : 'Total';

  return `
        <div class="invoice-header">
            <div class="invoice-header-left">
                <img src="/static/logo.png" alt="" class="invoice-logo" width="56" height="56">
                <div class="invoice-from">
                    <h2>Paul Banning</h2>
                    <p>48 Pellipar Close<br>
                    London N13 4AG<br>
                    07730 556097</p>
                </div>
            </div>
            <div class="text-end">
                <h1>QUOTE</h1>
                <p>Quote #: ${escapeHtml(quote.quote_number)}<br>
                Date: ${escapeHtml(formatUkDate(quote.date))}</p>
            </div>
        </div>

        <div class="invoice-details">
            <h4>Prepared for</h4>
            <p>${billToLines.join('<br>')}</p>
        </div>

        <table class="invoice-items">
            <thead>
                <tr>
                    <th style="width: 70%">Description</th>
                    <th style="width: 30%" class="text-end">${amtHeading}</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
                ${vatRows}
                <tr>
                    <td class="text-end" style="border-left: none; border-bottom: none;"><strong>${totalLabel}</strong></td>
                    <td class="text-end"><strong>£${Number(quote.total_amount).toFixed(2)}</strong></td>
                </tr>
            </tbody>
        </table>

        <div class="invoice-terms">
            <h5>Terms</h5>
            <p>This quote is valid for 30 days from the date shown. Prices are subject to availability and may be revised after this period.</p>
            <p>If you would like to proceed, please reply to confirm and we will issue an invoice.</p>
        </div>
    `;
}

async function openQuotePreview(quoteId) {
  try {
    const response = await apiFetch(`/api/quotes/${quoteId}`);
    if (!response.ok) throw new Error('Failed to load quote');
    const quote = await response.json();
    previewQuoteId = quote.id;

    const msg = document.getElementById('quoteEmailMessage');
    if (msg) msg.value = '';

    const preview = document.getElementById('quotePreview');
    preview.className = 'invoice-preview';
    preview.innerHTML = renderQuotePreviewHtml(quote);

    const modal = new bootstrap.Modal(document.getElementById('quotePreviewModal'));
    modal.show();
  } catch (error) {
    showError('Failed to open preview: ' + error.message);
  }
}

async function openEditQuote(quoteId) {
  try {
    const response = await apiFetch(`/api/quotes/${quoteId}`);
    if (!response.ok) throw new Error('Failed to load quote');
    const quote = await response.json();

    const form = document.getElementById('editQuoteForm');
    form.querySelector('input[name="quote_id"]').value = quote.id;
    form.querySelector('input[name="quote_number"]').value = quote.quote_number;
    form.querySelector('input[name="client_name"]').value = quote.client.name;

    const itemsContainer = document.getElementById('editQuoteItems');
    itemsContainer.innerHTML = `
            <div class="row mb-2">
                <div class="col-8">
                    <label class="form-label">Description</label>
                </div>
                <div class="col-4">
                    <label class="form-label">Amount (£)</label>
                </div>
            </div>
        `;

    quote.items.forEach((item) => addEditQuoteItem(item));

    const ev = document.getElementById('editQuoteVatApplies');
    const er = document.getElementById('editQuoteVatRate');
    if (ev) ev.checked = !!quote.vat_applies;
    if (er) {
      er.value =
        quote.vat_applies && quote.vat_rate_percent != null
          ? String(quote.vat_rate_percent)
          : '20';
    }
    syncEditQuoteVatUi();

    const modal = new bootstrap.Modal(document.getElementById('editQuoteModal'));
    modal.show();
  } catch (error) {
    showError('Failed to edit quote: ' + error.message);
  }
}

function addEditQuoteItem(item = null) {
  const container = document.getElementById('editQuoteItems');
  const newItem = document.createElement('div');
  newItem.className = 'line-item-row';
  newItem.innerHTML = `
        <div class="line-item-desc">
          <input type="text" class="form-control" name="description[]" placeholder="Description" required>
        </div>
        <div class="line-item-amt">
          <input type="number" step="0.01" class="form-control" name="amount[]" placeholder="0.00" required>
        </div>
        <div class="line-item-rm">
          <button type="button" class="btn-remove-line" aria-label="Remove line" onclick="removeLineItemRow(this)">×</button>
        </div>
    `;
  const descInput = newItem.querySelector('input[name="description[]"]');
  const amtInput = newItem.querySelector('input[name="amount[]"]');
  if (item) {
    descInput.value = item.description;
    amtInput.value = item.amount;
  }
  container.appendChild(newItem);
}

async function updateQuote() {
  try {
    const form = document.getElementById('editQuoteForm');
    const quoteId = form.querySelector('input[name="quote_id"]').value;
    const quoteNumber = (form.querySelector('input[name="quote_number"]').value || '').trim();
    const lineItems = collectLineItems('editQuoteItems');
    if (lineItems.error) {
      showError(lineItems.error);
      return;
    }

    const vatApplies = document.getElementById('editQuoteVatApplies')?.checked || false;
    const vatRateRaw = document.getElementById('editQuoteVatRate')?.value;
    const vatRatePercent = vatApplies ? parseFloat(vatRateRaw) : undefined;
    if (vatApplies && (Number.isNaN(vatRatePercent) || vatRatePercent < 0 || vatRatePercent > 100)) {
      showError('Enter a valid VAT rate between 0 and 100');
      return;
    }

    const response = await apiFetch(`/api/quotes/${quoteId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: lineItems.items,
        quote_number: quoteNumber,
        vat_applies: vatApplies,
        vat_rate_percent: vatRatePercent,
      }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to update quote');
    }

    showSuccess('Quote updated successfully');
    bootstrap.Modal.getInstance(document.getElementById('editQuoteModal')).hide();
    loadQuotes();
  } catch (error) {
    showError(error.message || 'Failed to update quote');
  }
}

async function deleteQuote(quoteId) {
  if (!confirm('Are you sure you want to delete this quote?')) return;

  try {
    const response = await apiFetch(`/api/quotes/${quoteId}`, {
      method: 'DELETE',
    });

    if (!response.ok) throw new Error('Failed to delete quote');

    showSuccess('Quote deleted successfully');
    loadQuotes();
  } catch (error) {
    showError('Failed to delete quote: ' + error.message);
  }
}

async function duplicateQuote(quoteId) {
  try {
    const response = await apiFetch(`/api/quotes/${quoteId}/duplicate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Failed to duplicate quote');
    }
    showSuccess(`Duplicated as ${data.quote_number}`);
    await loadQuotes();
    if (data.id) {
      openEditQuote(data.id);
    }
  } catch (error) {
    showError(error.message || 'Failed to duplicate quote');
  }
}

async function convertQuoteToInvoice(quoteId) {
  const id = quoteId || previewQuoteId;
  if (!id) {
    showError('Select a quote first');
    return;
  }
  if (!confirm('Create a new unpaid invoice from this quote?')) return;

  try {
    const response = await apiFetch(`/api/quotes/${id}/convert-to-invoice`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Failed to convert quote');
    }

    const previewModal = document.getElementById('quotePreviewModal');
    const modalInstance = previewModal ? bootstrap.Modal.getInstance(previewModal) : null;
    if (modalInstance) modalInstance.hide();

    showSuccess(`Quote ${data.quote_number} converted to invoice ${data.invoice_number}`);
    switchSection('invoices');
    switchInvoiceFilter('unpaid');
    await loadInvoices();
    if (data.id) {
      openEditInvoice(data.id);
    }
  } catch (error) {
    showError(error.message || 'Failed to convert quote');
  }
}

async function loadQuotes() {
  try {
    const response = await apiFetch('/api/quotes');
    if (!response.ok) throw new Error('Failed to load quotes');
    const quotes = await response.json();

    const list = document.getElementById('quotesList');
    if (!list) return;
    list.innerHTML = '';

    if (quotes.length === 0) {
      list.innerHTML = '<div class="empty-state">No quotes yet. Create a client, then make your first quote.</div>';
      return;
    }

    quotes.forEach((quote) => {
      const item = document.createElement('div');
      item.className = 'invoice-card';
      item.innerHTML = `
                <div class="invoice-card-main">
                    <p class="invoice-card-title">${escapeHtml(quote.quote_number)} — ${escapeHtml(quote.client.name)}</p>
                    <p class="invoice-card-meta">Date: ${escapeHtml(formatUkDate(quote.date))}</p>
                    ${
                      quote.vat_applies
                        ? `<p class="invoice-card-vat">VAT ${Number(quote.vat_rate_percent ?? 20).toFixed(2)}% · Net £${Number(
                            quote.subtotal_net ?? 0
                          ).toFixed(2)}</p>`
                        : ''
                    }
                    <p class="invoice-card-amount">£${Number(quote.total_amount).toFixed(2)}</p>
                </div>
                <div class="invoice-card-actions">
                    <button type="button" class="btn-apple-icon" title="Preview" aria-label="Preview" onclick="openQuotePreview(${quote.id})">
                        <i class="fas fa-eye"></i>
                    </button>
                    <button type="button" class="btn-apple-icon" title="Edit" aria-label="Edit" onclick="openEditQuote(${quote.id})">
                        <i class="fas fa-pen"></i>
                    </button>
                    <button type="button" class="btn-apple-icon" title="Duplicate" aria-label="Duplicate" onclick="duplicateQuote(${quote.id})">
                        <i class="fas fa-copy"></i>
                    </button>
                    <button type="button" class="btn-apple-icon is-convert" title="Convert to invoice" aria-label="Convert to invoice" onclick="convertQuoteToInvoice(${quote.id})">
                        <i class="fas fa-file-invoice"></i>
                    </button>
                    <button type="button" class="btn-apple-icon is-danger" title="Delete" aria-label="Delete" onclick="deleteQuote(${quote.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
      list.appendChild(item);
    });
  } catch (error) {
    showError('Failed to load quotes: ' + error.message);
  } finally {
    loadSummary();
  }
}

async function sendQuoteEmail() {
  if (!previewQuoteId) {
    showError('Open a quote preview first');
    return;
  }
  const btn = document.getElementById('btnSendQuote');
  if (btn) {
    btn.disabled = true;
  }
  try {
    const msgEl = document.getElementById('quoteEmailMessage');
    const message = (msgEl?.value || '').trim();
    const response = await apiFetch(`/api/quotes/${previewQuoteId}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Send failed');
    }
    showSuccess('Quote sent to client email');
  } catch (error) {
    showError(error.message || 'Failed to send email');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function printQuote() {
  const el = document.querySelector('#quotePreviewModal .invoice-preview');
  if (!el) return;

  const quoteContent = el.cloneNode(true);
  const printContainer = document.createElement('div');
  printContainer.className = 'print-container';
  printContainer.style.cssText = `
        position: fixed;
        left: 0;
        top: 0;
        width: 100%;
        max-width: 210mm;
        height: auto;
        min-height: 0;
        padding: 0;
        margin: 0;
        background-color: white;
        z-index: 9999;
        overflow: visible;
    `;

  printContainer.appendChild(quoteContent);
  document.body.appendChild(printContainer);

  setTimeout(() => {
    window.print();
    document.body.removeChild(printContainer);
  }, 200);
}

function saveQuotePDF() {
  printQuote();
}

function showSuccess(message) {
  const alertDiv = document.createElement('div');
  alertDiv.className = 'alert app-toast alert-success alert-dismissible fade show position-fixed top-0 end-0 m-3';
  alertDiv.style.zIndex = '11000';
  alertDiv.innerHTML = `
        ${escapeHtml(message)}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
  document.body.appendChild(alertDiv);
  setTimeout(() => alertDiv.remove(), 5000);
}

function showError(message) {
  const alertDiv = document.createElement('div');
  alertDiv.className = 'alert app-toast alert-danger alert-dismissible fade show position-fixed top-0 end-0 m-3';
  alertDiv.style.zIndex = '11000';
  alertDiv.innerHTML = `
        ${escapeHtml(message)}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
  document.body.appendChild(alertDiv);
  setTimeout(() => alertDiv.remove(), 8000);
}
