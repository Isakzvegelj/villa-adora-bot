/* ============================================
   Villa Pomona — Enhanced JavaScript
   ============================================ */

(function() {
    'use strict';

    // ===== State =====
    let currentLang = 'en';
    let currentSlide = 0;
    let currentTestimonial = 0;
    let currentLightboxIndex = 0;
    let isChatOpen = false;

    const galleryImages = [
        'assets/images/gallery-1.jpg',
        'assets/images/gallery-2.jpg',
        'assets/images/gallery-3.jpg',
        'assets/images/gallery-4.jpg',
        'assets/images/gallery-5.jpg',
        'assets/images/gallery-6.jpg',
    ];

    const chatResponses = {
        en: {
            booking: "To make a reservation, please fill out the reservation form below or call us at +386 51 603 858. You can also email evita.vilebled@gmail.com.",
            rooms: "We offer 7 elegant rooms across three categories: Standard (€120/night), Deluxe (€180/night), and Family (€220/night). Each room features unique historic charm with modern amenities.",
            wellness: "Our wellness area includes a Finnish sauna, massage services, and a relaxation room with garden views. Wellness access is included for all guests.",
            location: "We're located at Črtomirova ulica 2, 4260 Bled, Slovenia — just a 5-minute walk from Lake Bled and the town center.",
            breakfast: "A gourmet breakfast is included with every stay. We serve local, seasonal ingredients including homemade bread, fresh dairy, and organic produce.",
            parking: "Free private parking is available on-site for all guests.",
            wifi: "Free high-speed WiFi is available throughout the villa.",
            cancellation: "Free cancellation is available up to 48 hours before check-in. Late check-out is available upon request.",
            hiking: "Bled is a hiker's paradise! Popular trails include the 6 km lakeside path, the trail to Ojstrica viewpoint (30 min), and the Vintgar Gorge walk (25 min drive). The Julian Alps offer world-class trekking for all levels.",
            restaurants: "Bled has excellent dining options nearby. Try the famous Bled cream cake at Park Hotel, fresh fish at Ribca, or fine dining at Grad. The town center is just a 3-minute walk from the villa.",
            weather: "Bled has a mild continental climate. Summers (Jun-Aug) are warm (20-28°C) with occasional rain. Winters (Dec-Feb) are cold (-2 to 5°C) with snow. Spring and autumn are mild and beautiful for hiking.",
            pets: "We love pets! Please let us know in advance if you're bringing a furry friend. There's a small additional cleaning fee. The garden and lakeside paths are perfect for walks with your dog.",
            children: "Children are very welcome! We can provide extra beds, high chairs, and baby cots on request. The garden is safe for kids to play, and the lake is just a short walk away.",
            transport: "The nearest airport is Ljubljana Jože Pučnik (35 km). Bled has a train station on the Ljubljana-Jesenice line. Buses run regularly to Ljubljana (45 min). We can arrange airport transfers on request.",
            default: "Thank you for your message! For immediate assistance, please call +386 51 603 858 or email evita.vilebled@gmail.com. Is there anything specific I can help you with?"
        },
        sl: {
            booking: "Za rezervacijo izpolnite obrazec za rezervacijo spodaj ali nas pokličite na +386 51 603 858. Pišite tudi na evita.vilebled@gmail.com.",
            rooms: "Ponujamo 7 elegantnih sob v treh kategorijah: Standard (€120/noč), Deluxe (€180/noč) in Družinska (€220/noč). Vsaka soba ima edinstven zgodovinski šarm s sodobnim udobjem.",
            wellness: "Naš wellness center vključuje finsko savno, masažne storitve in sprostitveni prostor z razgledom na vrt. Dostop do wellnessa je vključen za vse goste.",
            location: "Nahajamo se na Črtomirovavi ulici 2, 4260 Bled — le 5 min hoje od Blejskega jega in centra mesta.",
            breakfast: "Gurmanski zajtrk je vključen pri vsakem bivanju. Serviramo lokalne, sezenske sestavine, vključno s domačim kruhom, svežo mlečno produkcijo in organskimi pridelki.",
            parking: "Brezplačno parkirišče je na voljo na lokaciji za vse goste.",
            wifi: "Brezplačen hitri WiFi je na voljo po celotni vili.",
            cancellation: "Brezplačna odpoved je možna do 48 ur pred prihodom. Pozen odhod je na voljo na zahtevo.",
            hiking: "Bled je raj za pohodnike! Priljubljene poti vključujejo 6 km ob jezeru, pot do razgledne točke Ojstrica (30 min) in sprehod po soteski Vintgar (25 min vožnje). Julijske Alpe ponujajo vrhunske pohodniške možnosti.",
            restaurants: "Bled ima odlične restavracije v bližini. Poskusite sladico Blejska kremšnita v Park Hotelu, sveže ribe v Ribci ali fino kuhinjo v Gradu. Center mesta je le 3 min hoje od vile.",
            weather: "Bled ima zmerno celinsko podnebje. Poletja (jun-avg) so topla (20-28°C) z občasnimi deževji. Zime (dec-feb) so hladne (-2 do 5°C) s snegom. Pomlad in jesen sta mirna in lepa za pohodništvo.",
            pets: "Imamo radi živali! Prosimo, obvestite nas vnaprej, če bostes psa. Obstaja majhna dodatna pristojbina za čiščenje. Vrt in obalne poti so popolni za sprehode s psom.",
            children: "Otroci so dobrodošli! Na zahtevo lahko zagotovimo dodatne postelje, visoke stole in otroške posteljice. Vrt je varen za igro, jezero pa je le kratka hoja stran.",
            transport: "Najbližje letališče je Ljubljana Jože Pučnik (35 km). Bled ima železniško postajo na progi Ljubljana-Jesenice. Avtobusi vozijo redno do Ljubljane (45 min). Prevoz od letališča lahko uredimo na zahtevo.",
            default: "Hvala za vaše sporočilo! Za takojšnjo pomoč pokličite +386 51 603 858 ali pišite na evita.vilebled@gmail.com. Vam lahko pomagam s čim?"
        }
    };

    // ===== Document Ready =====
    document.addEventListener('DOMContentLoaded', function() {
        initHeader();
        initHeroSlider();
        initTestimonials();
        initGallery();
        initScrollReveal();
        initDateInputs();
        initPlaceholders();
    });

    // ===== Header Scroll Effect =====
    function initHeader() {
        const header = document.getElementById('header');
        if (!header) return;
        
        let lastScroll = 0;
        
        window.addEventListener('scroll', function() {
            const scrollY = window.scrollY;
            
            if (scrollY > 50) {
                header.classList.add('scrolled');
            } else {
                header.classList.remove('scrolled');
            }
            
            lastScroll = scrollY;
        }, { passive: true });
    }

    // ===== Mobile Menu =====
    window.toggleMobileMenu = function() {
        const menu = document.getElementById('navMenu');
        const btn = document.querySelector('.mobile-menu-btn');
        if (!menu || !btn) return;
        
        menu.classList.toggle('open');
        btn.classList.toggle('active');
        btn.setAttribute('aria-expanded', btn.classList.contains('active'));
    };

    // ===== Hero Slider =====
    function initHeroSlider() {
        const slides = document.querySelectorAll('.hero-slide');
        if (slides.length === 0) return;
        
        // Create dots
        const dotsContainer = document.getElementById('sliderDots');
        if (dotsContainer) {
            slides.forEach((_, i) => {
                const dot = document.createElement('button');
                dot.className = 'slider-dot' + (i === 0 ? ' active' : '');
                dot.setAttribute('aria-label', 'Go to slide ' + (i + 1));
                dot.addEventListener('click', function() { goToSlide(i); });
                dotsContainer.appendChild(dot);
            });
        }
        
        // Auto-advance
        setInterval(function() {
            changeSlide(1);
        }, 6000);
    }

    window.changeSlide = function(dir) {
        const slides = document.querySelectorAll('.hero-slide');
        const dots = document.querySelectorAll('.slider-dot');
        if (slides.length === 0) return;
        
        slides[currentSlide].classList.remove('active');
        if (dots[currentSlide]) dots[currentSlide].classList.remove('active');
        
        currentSlide = (currentSlide + dir + slides.length) % slides.length;
        
        slides[currentSlide].classList.add('active');
        if (dots[currentSlide]) dots[currentSlide].classList.add('active');
    };

    function goToSlide(index) {
        const slides = document.querySelectorAll('.hero-slide');
        const dots = document.querySelectorAll('.slider-dot');
        if (slides.length === 0 || index === currentSlide) return;
        
        slides[currentSlide].classList.remove('active');
        if (dots[currentSlide]) dots[currentSlide].classList.remove('active');
        
        currentSlide = index;
        
        slides[currentSlide].classList.add('active');
        if (dots[currentSlide]) dots[currentSlide].classList.add('active');
    }

    // ===== Testimonials =====
    function initTestimonials() {
        const cards = document.querySelectorAll('.testimonial-card');
        if (cards.length === 0) return;
        
        const dotsContainer = document.getElementById('testimonialDots');
        if (dotsContainer) {
            cards.forEach((_, i) => {
                const dot = document.createElement('button');
                dot.className = 't-dot' + (i === 0 ? ' active' : '');
                dot.setAttribute('aria-label', 'Testimonial ' + (i + 1));
                dot.addEventListener('click', function() { goToTestimonial(i); });
                dotsContainer.appendChild(dot);
            });
        }
        
        setInterval(function() {
            goToTestimonial((currentTestimonial + 1) % cards.length);
        }, 5000);
    }

    function goToTestimonial(index) {
        const cards = document.querySelectorAll('.testimonial-card');
        const dots = document.querySelectorAll('.t-dot');
        if (cards.length === 0 || index === currentTestimonial) return;
        
        cards[currentTestimonial].classList.remove('active');
        if (dots[currentTestimonial]) dots[currentTestimonial].classList.remove('active');
        
        currentTestimonial = index;
        
        cards[currentTestimonial].classList.add('active');
        if (dots[currentTestimonial]) dots[currentTestimonial].classList.add('active');
    }

    // ===== Gallery & Lightbox =====
    function initGallery() {
        // Keyboard navigation for lightbox
        document.addEventListener('keydown', function(e) {
            const lightbox = document.getElementById('lightbox');
            if (!lightbox || !lightbox.classList.contains('active')) return;
            
            if (e.key === 'Escape') closeLightbox();
            if (e.key === 'ArrowLeft') changeLightbox(-1);
            if (e.key === 'ArrowRight') changeLightbox(1);
        });
    }

    window.openLightbox = function(index) {
        currentLightboxIndex = index;
        const lightbox = document.getElementById('lightbox');
        const img = document.getElementById('lightboxImg');
        if (!lightbox || !img) return;
        
        img.src = galleryImages[index];
        img.alt = 'Gallery image ' + (index + 1);
        lightbox.classList.add('active');
        document.body.style.overflow = 'hidden';
    };

    window.closeLightbox = function() {
        const lightbox = document.getElementById('lightbox');
        if (!lightbox) return;
        
        lightbox.classList.remove('active');
        document.body.style.overflow = '';
    };

    window.changeLightbox = function(dir) {
        currentLightboxIndex = (currentLightboxIndex + dir + galleryImages.length) % galleryImages.length;
        const img = document.getElementById('lightboxImg');
        if (img) {
            img.src = galleryImages[currentLightboxIndex];
            img.alt = 'Gallery image ' + (currentLightboxIndex + 1);
        }
    };

    // ===== Scroll Reveal =====
    function initScrollReveal() {
        const elements = document.querySelectorAll('.room-card, .contact-card, .feature-item, .wellness-item, .reservation-form, .room-card');
        
        if ('IntersectionObserver' in window) {
            const observer = new IntersectionObserver(function(entries) {
                entries.forEach(function(entry, i) {
                    if (entry.isIntersecting) {
                        setTimeout(function() {
                            entry.target.classList.add('visible');
                        }, (i % 3) * 150);
                        observer.unobserve(entry.target);
                    }
                });
            }, {
                threshold: 0.1,
                rootMargin: '0px 0px -50px 0px'
            });
            
            elements.forEach(function(el) {
                el.classList.add('reveal');
                observer.observe(el);
            });
        } else {
            elements.forEach(function(el) {
                el.classList.add('visible');
            });
        }
    }

    // ===== Date Inputs =====
    function initDateInputs() {
        const checkIn = document.getElementById('checkIn');
        const checkOut = document.getElementById('checkOut');
        if (!checkIn || !checkOut) return;
        
        const today = new Date().toISOString().split('T')[0];
        checkIn.min = today;
        
        checkIn.addEventListener('change', function() {
            if (this.value) {
                const nextDay = new Date(this.value);
                nextDay.setDate(nextDay.getDate() + 1);
                checkOut.min = nextDay.toISOString().split('T')[0];
                
                if (checkOut.value && checkOut.value <= this.value) {
                    checkOut.value = checkOut.min;
                }
            }
        });
    }

    // ===== Placeholders =====
    function initPlaceholders() {
        applyPlaceholders(currentLang);
    }

    function applyPlaceholders(lang) {
        document.querySelectorAll('[data-placeholder-' + lang + ']').forEach(function(el) {
            el.placeholder = el.getAttribute('data-placeholder-' + lang);
        });
    }

    // ===== Language Switching =====
    window.switchLanguage = function(lang) {
        currentLang = lang;
        
        // Update buttons
        document.querySelectorAll('.lang-btn').forEach(function(btn) {
            btn.classList.remove('active');
        });
        
        var langBtns = document.querySelectorAll('.lang-btn');
        langBtns.forEach(function(btn) {
            if (btn.getAttribute('onclick').indexOf("'" + lang + "'") !== -1) {
                btn.classList.add('active');
            }
        });
        
        // Update text content
        document.querySelectorAll('[data-lang-' + lang + ']').forEach(function(el) {
            if (el.children.length === 0) {
                el.textContent = el.getAttribute('data-lang-' + lang);
            }
        });
        
        // Update placeholders
        applyPlaceholders(lang);
        
        // Update chat messages
        const chatMessages = document.querySelectorAll('.chat-message.bot p');
        if (chatMessages.length > 0) {
            var welcomeMsg = chatResponses[lang].default.split('.')[0];
            // Only update the first bot message
            if (chatMessages[0].getAttribute('data-lang-' + lang)) {
                chatMessages[0].textContent = chatMessages[0].getAttribute('data-lang-' + lang);
            }
        }
    };

    // ===== Reservation Form =====
    window.handleReservationSubmit = function(e) {
        e.preventDefault();
        
        const form = document.getElementById('reservationForm');
        const btn = document.getElementById('submitBtn');
        if (!form || !btn) return;
        
        // Validate
        const checkIn = document.getElementById('checkIn').value;
        const checkOut = document.getElementById('checkOut').value;
        
        if (checkIn && checkOut && checkIn >= checkOut) {
            alert(currentLang === 'sl' ? 'Datum odhoda mora biti po datumu prihoda.' : 'Check-out must be after check-in.');
            return;
        }
        
        // Show loading
        const originalText = btn.textContent;
        btn.textContent = currentLang === 'sl' ? 'Pošiljanje...' : 'Sending...';
        btn.disabled = true;
        btn.style.opacity = '0.7';
        
        // Simulate submission
        setTimeout(function() {
            btn.textContent = currentLang === 'sl' ? '✓ Poslano!' : '✓ Sent!';
            btn.style.background = '#2d8a4e';
            btn.style.borderColor = '#2d8a4e';
            
            setTimeout(function() {
                btn.textContent = originalText;
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.style.background = '';
                btn.style.borderColor = '';
                form.reset();
            }, 3000);
        }, 1500);
    };

    // ===== Chat Widget =====
    window.toggleChat = function() {
        const widget = document.getElementById('chatWidget');
        if (!widget) return;
        
        isChatOpen = !isChatOpen;
        
        if (isChatOpen) {
            widget.classList.add('open');
            setTimeout(function() {
                var input = document.getElementById('chatInput');
                if (input) input.focus();
            }, 300);
        } else {
            widget.classList.remove('open');
        }
    };

    window.sendChatMessage = function() {
        var input = document.getElementById('chatInput');
        var messages = document.getElementById('chatMessages');
        if (!input || !messages || !input.value.trim()) return;
        
        var userMsg = input.value.trim();
        input.value = '';
        
        // Add user message
        var userDiv = document.createElement('div');
        userDiv.className = 'chat-message user';
        userDiv.innerHTML = '<p>' + escapeHtml(userMsg) + '</p>';
        messages.appendChild(userDiv);
        
        // Find response
        var response = getBotResponse(userMsg.toLowerCase());
        
        // Add bot response with delay
        setTimeout(function() {
            var botDiv = document.createElement('div');
            botDiv.className = 'chat-message bot';
            botDiv.innerHTML = '<p>' + response + '</p>';
            messages.appendChild(botDiv);
            messages.scrollTop = messages.scrollHeight;
        }, 800);
        
        messages.scrollTop = messages.scrollHeight;
    };

    window.handleChatKeypress = function(e) {
        if (e.key === 'Enter') {
            sendChatMessage();
        }
    };

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    function getBotResponse(message) {
        var responses = chatResponses[currentLang] || chatResponses.en;
        var msg = message.toLowerCase();
        
        if (msg.indexOf('book') !== -1 || msg.indexOf('reserve') !== -1 || msg.indexOf('rezerv') !== -1 || msg.indexOf('cena') !== -1 || msg.indexOf('price') !== -1 || msg.indexOf('cost') !== -1) {
            return responses.booking;
        }
        if (msg.indexOf('room') !== -1 || msg.indexOf('sob') !== -1 || msg.indexOf('suite') !== -1 || msg.indexOf('apart') !== -1) {
            return responses.rooms;
        }
        if (msg.indexOf('wellness') !== -1 || msg.indexOf('sauna') !== -1 || msg.indexOf('spa') !== -1 || msg.indexOf('savn') !== -1 || msg.indexOf('masa') !== -1 || msg.indexOf('massage') !== -1) {
            return responses.wellness;
        }
        if (msg.indexOf('where') !== -1 || msg.indexOf('location') !== -1 || msg.indexOf('address') !== -1 || msg.indexOf('kje') !== -1 || msg.indexOf('naslov') !== -1 || msg.indexOf('lokac') !== -1) {
            return responses.location;
        }
        if (msg.indexOf('breakfast') !== -1 || msg.indexOf('food') !== -1 || msg.indexOf('zajtrk') !== -1 || msg.indexOf('hrana') !== -1 || msg.indexOf('jed') !== -1) {
            return responses.breakfast;
        }
        if (msg.indexOf('parking') !== -1 || msg.indexOf('park') !== -1 || msg.indexOf('parkir') !== -1 || msg.indexOf('car') !== -1 || msg.indexOf('auto') !== -1) {
            return responses.parking;
        }
        if (msg.indexOf('wifi') !== -1 || msg.indexOf('internet') !== -1) {
            return responses.wifi;
        }
        if (msg.indexOf('cancel') !== -1 || msg.indexOf('odpov') !== -1 || msg.indexOf('refund') !== -1) {
            return responses.cancellation;
        }
        if (msg.indexOf('hiking') !== -1 || msg.indexOf('walk') !== -1 || msg.indexOf('trail') !== -1 || msg.indexOf('pohod') !== -1 || msg.indexOf('pot') !== -1 || msg.indexOf('gore') !== -1 || msg.indexOf('mountain') !== -1) {
            return responses.hiking;
        }
        if (msg.indexOf('restaurant') !== -1 || msg.indexOf('eat') !== -1 || msg.indexOf('dinner') !== -1 || msg.indexOf('lunch') !== -1 || msg.indexOf('restavrac') !== -1 || msg.indexOf('jest') !== -1 || msg.indexOf('večerja') !== -1) {
            return responses.restaurants;
        }
        if (msg.indexOf('weather') !== -1 || msg.indexOf('temperature') !== -1 || msg.indexOf('climate') !== -1 || msg.indexOf('vreme') !== -1) {
            return responses.weather;
        }
        if (msg.indexOf('dog') !== -1 || msg.indexOf('pet') !== -1 || msg.indexOf('pes') !== -1 || msg.indexOf('pesek') !== -1) {
            return responses.pets;
        }
        if (msg.indexOf('child') !== -1 || msg.indexOf('kid') !== -1 || msg.indexOf('baby') !== -1 || msg.indexOf('otro') !== -1 || msg.indexOf('družin') !== -1) {
            return responses.children;
        }
        if (msg.indexOf('transport') !== -1 || msg.indexOf('bus') !== -1 || msg.indexOf('train') !== -1 || msg.indexOf('airport') !== -1 || msg.indexOf('prevoz') !== -1 || msg.indexOf('letali') !== -1) {
            return responses.transport;
        }
        
        return responses.default;
    }

    // ===== Newsletter Form =====
    window.handleNewsletterSubmit = function(e) {
        e.preventDefault();
        const email = document.getElementById('newsletterEmail').value;
        if (!email) return;

        const btn = e.target.querySelector('button');
        const originalText = btn.textContent;
        btn.textContent = currentLang === 'sl' ? '✓ Prijavljeni!' : '✓ Subscribed!';
        btn.style.background = '#2d8a4e';
        btn.style.borderColor = '#2d8a4e';

        setTimeout(function() {
            btn.textContent = originalText;
            btn.style.background = '';
            btn.style.borderColor = '';
            document.getElementById('newsletterEmail').value = '';
        }, 3000);
    };

    // ===== Smooth Scroll for Anchor Links =====
    document.addEventListener('click', function(e) {
        var anchor = e.target.closest('a[href^="#"]');
        if (!anchor) return;
        
        var targetId = anchor.getAttribute('href');
        if (targetId === '#') return;
        
        var target = document.querySelector(targetId);
        if (target) {
            // Don't prevent default for reservation - let the form work
            // But do smooth scroll
            
            var headerHeight = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--header-height')) || 70;
            var targetPosition = target.getBoundingClientRect().top + window.scrollY - headerHeight;
            
            window.scrollTo({
                top: targetPosition,
                behavior: 'smooth'
            });
        }
    });

})();
