
      const state = {
        filter: 'All',
        query: '',
        crops: [],
        demand: [],
        user: null,
        watchlist: new Set(),
        savedFields: [],
        currentFieldId: null,
        latestSeasonalResult: null
      };

      const rupees = (n) => '₹' + Number(n).toLocaleString('en-IN');

      function spark(vals, color = '#c5df7a') {
        const w = 86;
        const h = 28;
        const min = Math.min(...vals);
        const max = Math.max(...vals);
        const pts = vals.map((v, i) => `${i * w / (vals.length - 1)},${h - 3 - ((v - min) / (max - min || 1)) * (h - 7)}`).join(' ');
        return `<svg class="mini-chart" viewBox="0 0 ${w} ${h}" aria-label="7 day indicative trend"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/><circle cx="${w}" cy="${h - 3 - ((vals.at(-1) - min) / (max - min || 1)) * (h - 7)}" r="2.5" fill="${color}"/></svg>`;
      }

      function renderTicker() {
        const items = state.crops.slice(0, 3);
        document.querySelector('#tickerItems').innerHTML = items.map((crop) => `
          <div class="ticker-item">
            <div class="crop-name">${crop.name} <span style="color:#727a6d">· ${crop.local_name}</span></div>
            <div class="crop-price">${rupees(crop.price)}</div>
            <div class="crop-change">${crop.change >= 0 ? '▲' : '▼'} ${Math.abs(crop.change).toFixed(1)}% / indicative</div>
          </div>
        `).join('');
      }

      function renderCrops() {
        const rows = state.crops.filter((crop) => {
          const matchesFilter = state.filter === 'All' || crop.category === state.filter;
          const haystack = `${crop.name} ${crop.local_name} ${crop.market || ''} ${crop.location || ''}`.toLowerCase();
          return matchesFilter && haystack.includes(state.query);
        });

        document.querySelector('#cropRows').innerHTML = rows.map((crop) => `
          <tr>
            <td>
              <div class="commodity">
                <span class="crop-icon">${crop.icon}</span>
                <span>
                  <strong>${crop.name}</strong>
                  <small>${crop.local_name || crop.name} · ${crop.category}</small>
                </span>
              </div>
            </td>
            <td class="price">${rupees(crop.price)}</td>
            <td class="${crop.change >= 0 ? 'change-up' : 'change-down'}">${crop.change >= 0 ? '▲' : '▼'} ${Math.abs(crop.change).toFixed(1)}%</td>
            <td>${spark(crop.trend, crop.change >= 0 ? '#c5df7a' : '#cf896c')}</td>
            <td>${crop.market}</td>
            <td><button class="action-link watch" type="button" data-id="${crop.id}">${state.watchlist.has(crop.id) ? '★ Watching' : '☆ Watch'}</button></td>
          </tr>
        `).join('') || '<tr><td colspan="6" class="empty-row">No matching crops. Try another search.</td></tr>';
      }

      function renderDemand() {
        document.querySelector('#demandRows').innerHTML = state.demand.map((d, i) => `
          <tr>
            <td>
              <div class="commodity">
                <span class="crop-icon">0${i + 1}</span>
                <span>
                  <strong>${d.crop_name}</strong>
                  <small>${d.detail}</small>
                </span>
              </div>
            </td>
            <td class="price">${d.quantity}</td>
            <td>${d.place}</td>
            <td>${d.delivery}</td>
            <td><span class="tag">${d.quality}</span></td>
            <td><button class="action-link quote" type="button" data-crop="${d.crop_name.split(' · ')[0]}">Respond ↗</button></td>
          </tr>
        `).join('');

        document.querySelector('#sideDemand').innerHTML = state.demand.slice(0, 2).map((d) => `
          <div class="demand-item">
            <div>
              <strong>${d.crop_name}</strong>
              <p>${d.place} · ${d.delivery}</p>
            </div>
            <div class="qty">${d.quantity}<small>BUYER NEED</small></div>
          </div>
        `).join('');
      }

      function renderInsights(data) {
        document.querySelector('#insightWatchCount').textContent = data.watchlist_count;
        document.querySelector('#insightInquiryCount').textContent = data.inquiries_count;
        const average = data.average_change_pct;
        const averageEl = document.querySelector('#insightAverageChange');
        averageEl.textContent = average === null ? '—' : `${average >= 0 ? '+' : ''}${average.toFixed(1)}%`;
        averageEl.classList.toggle('change-down', average !== null && average < 0);
        averageEl.classList.toggle('change-up', average !== null && average >= 0);

        const list = document.querySelector('#insightRows');
        list.replaceChildren();
        const addInsight = (title, detail, type = 'context') => {
          const item = document.createElement('article');
          item.className = `insight-item insight-${type}`;
          const heading = document.createElement('strong');
          heading.textContent = title;
          const body = document.createElement('p');
          body.textContent = detail;
          item.append(heading, body);
          list.append(item);
        };

        if (data.watchlist_count === 0) {
          addInsight('Start with crops you follow', 'Use ☆ Watch in the price table to build your personal market view.');
        } else if (data.insights.length === 0) {
          addInsight('Your watchlist is ready', 'No matching buyer demand or sufficient price history is available yet.');
        } else {
          data.insights.forEach((insight) => {
            addInsight(`${insight.crop} · ${insight.title}`, insight.detail, insight.type);
          });
        }
        addInsight('Data availability', data.data_note);
      }

      async function loadSavedFields() {
        const select = document.querySelector('#savedFieldSelect');
        const loadButton = document.querySelector('#loadSavedField');
        if (!state.user) {
          state.savedFields = [];
          state.currentFieldId = null;
          state.latestSeasonalResult = null;
          select.replaceChildren(new Option('Your saved fields', ''));
          loadButton.disabled = true;
          document.querySelector('#saveFieldAnalysis').disabled = true;
          document.querySelector('#fieldSaveStatus').textContent = 'Sign in to save fields and analysis history.';
          document.querySelector('#savedAnalysisHistory').replaceChildren();
          return;
        }

        const response = await fetch('/api/fields');
        const fields = await response.json();
        if (!response.ok) throw new Error(fields.error || 'Unable to load saved fields');
        state.savedFields = fields;
        const selectedId = String(state.currentFieldId || '');
        select.replaceChildren(new Option('Choose a saved field', ''));
        fields.forEach((field) => select.add(new Option(`${field.name} · ${field.analysis_count} analyses`, field.id)));
        select.value = fields.some((field) => String(field.id) === selectedId) ? selectedId : '';
        loadButton.disabled = !select.value;
        document.querySelector('#saveFieldAnalysis').disabled = !state.latestSeasonalResult;
        document.querySelector('#fieldSaveStatus').textContent = fields.length
          ? `${fields.length} saved field${fields.length === 1 ? '' : 's'} · field and history are private to your account.`
          : 'No saved fields yet. Give your plot a name to save this analysis.';
      }

      async function loadUserContext() {
        const response = await fetch('/api/me');
        const account = await response.json();
        const signin = document.querySelector('#signin');
        if (!account.logged_in) {
          state.user = null;
          state.watchlist.clear();
          signin.textContent = 'Sign in';
          document.querySelector('#insightStatus').textContent = 'Sign in to see insights for your account.';
          document.querySelector('#insightWatchCount').textContent = '—';
          document.querySelector('#insightInquiryCount').textContent = '—';
          document.querySelector('#insightAverageChange').textContent = '—';
          document.querySelector('#insightRows').replaceChildren();
          await loadSavedFields();
          renderCrops();
          return;
        }

        state.user = account.user;
        signin.textContent = `Hi, ${account.user.full_name}`;
        const [watchlistResponse, insightsResponse] = await Promise.all([
          fetch('/api/watchlist'),
          fetch('/api/insights')
        ]);
        if (!watchlistResponse.ok || !insightsResponse.ok) {
          throw new Error('Unable to load your personalized insights');
        }
        const [watchlistData, insightData] = await Promise.all([
          watchlistResponse.json(),
          insightsResponse.json()
        ]);
        state.watchlist = new Set(watchlistData.items);
        document.querySelector('#insightStatus').textContent = `Personalized for ${account.user.full_name}`;
        renderCrops();
        renderInsights(insightData);
        await loadSavedFields();
      }

      async function loadData() {
        const [cropsRes, demandRes, weatherRes, marketsRes] = await Promise.all([
          fetch('/api/crops'),
          fetch('/api/demand'),
          fetch('/api/weather'),
          fetch('/api/markets')
        ]);

        state.crops = await cropsRes.json();
        state.demand = await demandRes.json();
        const weather = await weatherRes.json();
        const marketData = await marketsRes.json();

        renderTicker();
        renderCrops();
        renderDemand();
        renderWeather(weather);
        renderMapMarkets(marketData);
        await loadUserContext();
      }

      function renderWeather(data) {
        const current = data.current || {};
        const forecast = data.forecast || [];

        document.querySelector('#weatherTemp').textContent = `${Math.round(current.temp || 0)}°`;
        document.querySelector('#weatherCondition').textContent = current.description || 'Unavailable';
        document.querySelector('#weatherHumidity').textContent = `${current.humidity || 0}%`;
        document.querySelector('#weatherWind').textContent = `${Math.round(current.windSpeed || 0)} km/h`;
        document.querySelector('#weatherIcon').textContent = weatherIcon(current.iconCode || 800);
        document.querySelector('#weatherState').textContent = `OpenWeather · updated ${new Date((current.time || Date.now() / 1000) * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`;

        document.querySelector('#forecast').innerHTML = forecast.map((day) => `
          <div class="forecast-day">
            ${new Date(`${day.date}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short' })}
            <span class="ficon" aria-hidden="true">${weatherIcon(day.iconCode)}</span>
            <b>${Math.round(day.max)}° / ${Math.round(day.min)}°</b>
            <small>${day.description}</small>
          </div>
        `).join('');
      }

      function weatherIcon(code) {
        if (code < 300) return 'ϟ';
        if (code < 600) return '☂';
        if (code < 700) return '❄';
        if (code === 800) return '☀';
        return '☁';
      }

      function toast(msg) {
        const el = document.querySelector('#toast');
        el.textContent = msg;
        el.classList.add('show');
        clearTimeout(window.toastTimer);
        window.toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
      }

      document.querySelectorAll('.chip').forEach((button) => {
        button.addEventListener('click', () => {
          document.querySelectorAll('.chip').forEach((chip) => chip.classList.toggle('active', chip === button));
          state.filter = button.dataset.filter;
          renderCrops();
        });
      });

      document.querySelector('#search').addEventListener('input', (event) => {
        state.query = event.target.value.toLowerCase();
        renderCrops();
      });

      document.addEventListener('click', (event) => {
        const watch = event.target.closest('.watch');
        if (watch) {
          if (!state.user) {
            openAuthModal();
            toast('Sign in to save crops to your watchlist');
            return;
          }
          const cropId = Number(watch.dataset.id);
          const crop = state.crops.find((item) => item.id === cropId);
          const watching = state.watchlist.has(cropId);
          fetch('/api/watchlist', {
            method: watching ? 'DELETE' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ crop_id: cropId })
          })
            .then(async (res) => {
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || 'Watchlist update failed');
              if (watching) state.watchlist.delete(cropId);
              else state.watchlist.add(cropId);
              renderCrops();
              await loadUserContext();
              toast(watching ? `${crop.name} removed from your watchlist` : `${crop.name} added to your watchlist`);
            })
            .catch((error) => toast(error.message));
        }

        const quote = event.target.closest('.quote');
        if (quote) {
          fetch('/api/me').then((res) => res.json()).then((data) => {
            if (!data.logged_in) {
              openAuthModal();
              toast('Please sign in to send a quotation inquiry');
            } else {
              openInquiryModal(quote.dataset.crop);
            }
          });
        }
      });

      document.querySelector('#refreshWeather').addEventListener('click', () => {
        fetch('/api/weather').then(res => res.json()).then(renderWeather).catch(() => toast('Weather service unavailable'));
      });

      const authModal = document.querySelector('#authModal');
      const inquiryModal = document.querySelector('#inquiryModal');
      const loginForm = document.querySelector('#loginForm');
      const registerForm = document.querySelector('#registerForm');
      const authTabs = document.querySelectorAll('[data-auth-tab]');

      function setAuthTab(tab) {
        const isLogin = tab === 'login';
        authTabs.forEach((btn) => btn.classList.toggle('active', btn.dataset.authTab === tab));
        loginForm.classList.toggle('hidden', !isLogin);
        registerForm.classList.toggle('hidden', isLogin);
      }

      function openAuthModal() {
        authModal.classList.remove('hidden');
      }

      function closeAuthModal() {
        authModal.classList.add('hidden');
      }

      function openInquiryModal(cropName) {
        document.querySelector('#inquiryCrop').value = cropName;
        inquiryModal.classList.remove('hidden');
      }

      function closeInquiryModal() {
        inquiryModal.classList.add('hidden');
      }

      document.querySelector('#signin').addEventListener('click', () => {
        fetch('/api/me').then((res) => res.json()).then((data) => {
          if (data.logged_in) {
            fetch('/api/logout', { method: 'POST' })
              .then(() => loadUserContext())
              .then(() => toast('You are now logged out'))
              .catch((error) => toast(error.message));
          } else {
            openAuthModal();
          }
        });
      });

      document.querySelector('#closeAuth').addEventListener('click', closeAuthModal);
      document.querySelector('#closeInquiry').addEventListener('click', closeInquiryModal);
      authTabs.forEach((tab) => tab.addEventListener('click', () => setAuthTab(tab.dataset.authTab)));

      loginForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(loginForm).entries());
        fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }).then(async (res) => {
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'Login failed');
          document.querySelector('#signin').textContent = `Hi, ${data.user.full_name}`;
          closeAuthModal();
          loginForm.reset();
          await loadUserContext();
          toast('Logged in successfully');
        }).catch((error) => toast(error.message));
      });

      registerForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(registerForm).entries());
        fetch('/api/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }).then(async (res) => {
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'Registration failed');
          setAuthTab('login');
          registerForm.reset();
          toast('Account created. Please log in.');
        }).catch((error) => toast(error.message));
      });

      document.querySelector('#inquiryForm').addEventListener('submit', (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(event.target).entries());
        fetch('/api/inquiries', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }).then(async (res) => {
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'Inquiry failed');
          closeInquiryModal();
          event.target.reset();
          toast('Inquiry sent successfully');
          loadUserContext().catch((error) => toast(error.message));
        }).catch((error) => toast(error.message));
      });

      fetch('/api/me').then((res) => res.json()).then((data) => {
        if (data.logged_in) {
          loadUserContext().catch((error) => toast(error.message));
        }
      });

      document.querySelector('#refreshInsights').addEventListener('click', () => {
        loadUserContext().catch((error) => toast(error.message));
      });

      document.querySelector('#langBtn').addEventListener('click', () => toast('Hindi interface will be added in the next milestone'));

      function renderMapMarkets(markets) {
        if (!window.L) return;
        const dairyCenter = [25.5302806, 85.9195789];
  
