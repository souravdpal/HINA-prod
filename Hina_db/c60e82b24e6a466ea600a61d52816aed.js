// Default database seed values if client storage is empty
const defaultStudents = [
    { id: "SCH-10023", name: "Alexander Vance", email: "a.vance@university.edu", major: "Computer Science", gpa: 3.84, attendance: 92 },
    { id: "SCH-10024", name: "Sophia Martinez", email: "s.martinez@university.edu", major: "Data Science", gpa: 3.91, attendance: 95 },
    { id: "SCH-10025", name: "Evelyn Sterling", email: "e.sterling@university.edu", major: "Cyber Security", gpa: 3.76, attendance: 89 },
    { id: "SCH-10026", name: "Marcus Broady", email: "m.broady@university.edu", major: "Computer Science", gpa: 3.12, attendance: 78 },
    { id: "SCH-10027", name: "Gavin Deakin", email: "g.deakin@university.edu", major: "Information Systems", gpa: 3.45, attendance: 85 },
    { id: "SCH-10028", name: "Isabella Cruz", email: "i.cruz@university.edu", major: "Data Science", gpa: 4.00, attendance: 99 },
    { id: "SCH-10029", name: "Liam Kensington", email: "l.kensington@university.edu", major: "Cyber Security", gpa: 3.65, attendance: 81 },
    { id: "SCH-10030", name: "Nadia Petrov", email: "n.petrov@university.edu", major: "Computer Science", gpa: 3.58, attendance: 90 }
];

const defaultLectures = [
    { id: "LEC-301", code: "CS-402", title: "Advanced Algorithms & Optimization", professor: "Dr. Sarah Jenkins", date: "2025-05-15", time: "10:00", location: "Auditorium C", attendees: ["SCH-10023", "SCH-10024", "SCH-10026", "SCH-10028", "SCH-10030"] },
    { id: "LEC-302", code: "DS-210", title: "Big Data Processing & Mining Techniques", professor: "Prof. Alan Turing", date: "2025-05-16", time: "14:00", location: "Seminar Room B", attendees: ["SCH-10024", "SCH-10027", "SCH-10028"] },
    { id: "LEC-303", code: "CY-315", title: "Information Systems Security Protocol", professor: "Dr. Bruce Schneier", date: "2025-05-18", time: "09:30", location: "Cyber Security Lab 2", attendees: ["SCH-10025", "SCH-10029"] },
    { id: "LEC-304", code: "IS-101", title: "Systems Architecture Overview", professor: "Dr. Grace Hopper", date: "2025-05-20", time: "11:00", location: "Online (Zoom)", attendees: ["SCH-10023", "SCH-10027", "SCH-10030"] }
];

const defaultLogs = [
    { timestamp: "2025-05-10 08:30", action: "Database seeded with initial values." },
    { timestamp: "2025-05-10 09:12", action: "System administrator logged in." }
];

// Master Class for Database state management
class SystemState {
    constructor() {
        this.students = JSON.parse(localStorage.getItem('edu_students')) || defaultStudents;
        this.lectures = JSON.parse(localStorage.getItem('edu_lectures')) || defaultLectures;
        this.logs = JSON.parse(localStorage.getItem('edu_logs')) || defaultLogs;
        this.activeLectureId = null;
    }

    save() {
        localStorage.setItem('edu_students', JSON.stringify(this.students));
        localStorage.setItem('edu_lectures', JSON.stringify(this.lectures));
        localStorage.setItem('edu_logs', JSON.stringify(this.logs));
    }

    addLog(action) {
        const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 16);
        this.logs.unshift({ timestamp, action });
        this.save();
    }
}

const state = new SystemState();

// Core DOM Elements
const sidebar = document.getElementById('sidebar');
const openSidebarBtn = document.getElementById('open-sidebar');
const closeSidebarBtn = document.getElementById('close-sidebar');
const themeToggleBtn = document.getElementById('theme-toggle');
const pageTitle = document.getElementById('page-title');

// Navigation management
openSidebarBtn.addEventListener('click', () => sidebar.classList.add('open', 'translate-x-0'));
closeSidebarBtn.addEventListener('click', () => sidebar.classList.remove('open', 'translate-x-0'));

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const target = e.currentTarget.getAttribute('data-target');
        switchView(target);
        sidebar.classList.remove('open', 'translate-x-0');
    });
});

function switchView(tabId) {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        if(btn.getAttribute('data-target') === tabId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    document.querySelectorAll('.tab-content').forEach(section => {
        section.classList.add('hidden');
    });
    document.getElementById(tabId).classList.remove('hidden');
    pageTitle.textContent = tabId.charAt(0).toUpperCase() + tabId.slice(1) + (tabId === 'students' ? ' Database' : tabId === 'lectures' ? ' Portal' : '');
    
    if (tabId === 'dashboard') {
        renderDashboard();
    } else if (tabId === 'students') {
        renderStudents();
    } else if (tabId === 'lectures') {
        renderLectures();
    } else if (tabId === 'analytics') {
        renderAnalytics();
    }
}

// Global Dark Mode Management
if (localStorage.getItem('theme') === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
} else {
    document.documentElement.classList.remove('dark');
}

themeToggleBtn.addEventListener('click', () => {
    if (document.documentElement.classList.contains('dark')) {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('theme', 'light');
    } else {
        document.documentElement.classList.add('dark');
        localStorage.setItem('theme', 'dark');
    }
    renderAnalytics(); // Re-render charts for dark-theme contrast compatibility
});

// Modals Handling Utility
function toggleModal(modalId, show = true) {
    const modal = document.getElementById(modalId);
    if (show) {
        modal.classList.add('modal-show');
        modal.classList.remove('hidden');
    } else {
        modal.classList.remove('modal-show');
        setTimeout(() => modal.classList.add('hidden'), 200);
    }
}

document.querySelectorAll('.modal-close').forEach(closeBtn => {
    closeBtn.addEventListener('click', (e) => {
        const modal = e.target.closest('[id$="-modal"]');
        if (modal) toggleModal(modal.id, false);
    });
});

// ======================= DASHBOARD ENGINE =======================
function renderDashboard() {
    // Calculative Metrics
    const totalStudents = state.students.length;
    const totalLectures = state.lectures.length;
    
    const avgAttendance = Math.round(state.students.reduce((acc, curr) => acc + parseFloat(curr.attendance), 0) / (totalStudents || 1));
    const avgGPA = (state.students.reduce((acc, curr) => acc + parseFloat(curr.gpa), 0) / (totalStudents || 1)).toFixed(2);

    document.getElementById('stat-total-students').textContent = totalStudents;
    document.getElementById('stat-total-lectures').textContent = totalLectures;
    document.getElementById('stat-avg-attendance').textContent = avgAttendance + '%';
    document.getElementById('stat-avg-gpa').textContent = avgGPA;

    // Timeline Rendering
    const timeline = document.getElementById('schedule-timeline');
    timeline.innerHTML = '';
    
    // Sort chronologically
    const sortedLectures = [...state.lectures].sort((a, b) => new Date(a.date) - new Date(b.date)).slice(0, 3);

    sortedLectures.forEach(lec => {
        const div = document.createElement('div');
        div.className = "flex items-start gap-4 p-4 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors duration-200 border border-slate-100 dark:border-slate-800/70";
        div.innerHTML = `
            <div class="flex flex-col items-center justify-center p-3 w-14 bg-indigo-50 dark:bg-indigo-950/40 text-brand-600 dark:text-brand-400 rounded-xl font-bold">
                <span class="text-xs uppercase">${new Date(lec.date).toLocaleDateString('en-US', { month: 'short' })}</span>
                <span class="text-lg">${new Date(lec.date).getDate() + 1}</span>
            </div>
            <div class="flex-1">
                <div class="flex items-center gap-2">
                    <span class="px-2 py-0.5 text-xs font-bold uppercase rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">${lec.code}</span>
                    <span class="text-xs text-slate-400 font-medium"><i class="fa-regular fa-clock mr-1"></i>${lec.time}</span>
                </div>
                <h4 class="text-sm font-semibold mt-1 text-slate-800 dark:text-slate-200">${lec.title}</h4>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5"><i class="fa-solid fa-user-tie mr-1.5"></i>${lec.professor} • <i class="fa-solid fa-location-dot mx-1"></i>${lec.location}</p>
            </div>
        `;
        timeline.appendChild(div);
    });

    // Scholar Leaderboard
    const topScholars = [...state.students].sort((a, b) => b.gpa - a.gpa).slice(0, 3);
    const scholarsContainer = document.getElementById('top-scholars-list');
    scholarsContainer.innerHTML = '';

    topScholars.forEach((student, index) => {
        const medalColors = ["text-amber-500", "text-slate-400", "text-amber-700"];
        const div = document.createElement('div');
        div.className = "flex items-center justify-between p-3 rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40";
        div.innerHTML = `
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 flex items-center justify-center font-bold text-lg ${medalColors[index] || "text-slate-500"}">
                    ${index <= 2 ? `<i class="fa-solid fa-medal"></i>` : index+1}
                </div>
                <div>
                    <h4 class="text-sm font-bold text-slate-800 dark:text-slate-200">${student.name}</h4>
                    <p class="text-xs text-slate-400">${student.major}</p>
                </div>
            </div>
            <div class="text-right">
                <span class="px-2.5 py-1 text-xs font-extrabold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/50 rounded-lg">GPA ${student.gpa.toFixed(2)}</span>
            </div>
        `;
        scholarsContainer.appendChild(div);
    });
}

// ======================= STUDENT MANAGEMENT SYSTEM =======================
const searchInput = document.getElementById('search-student-db');
const filterMajor = document.getElementById('filter-major');
const globalSearch = document.getElementById('global-search');

function renderStudents() {
    const tableBody = document.getElementById('student-table-body');
    const emptyState = document.getElementById('student-empty-state');
    tableBody.innerHTML = '';

    const searchQuery = (searchInput.value || globalSearch.value).toLowerCase();
    const selectedMajor = filterMajor.value;

    const filtered = state.students.filter(student => {
        const matchesSearch = student.name.toLowerCase().includes(searchQuery) || student.id.toLowerCase().includes(searchQuery) || student.email.toLowerCase().includes(searchQuery);
        const matchesMajor = selectedMajor === 'All' || student.major === selectedMajor;
        return matchesSearch && matchesMajor;
    });

    if (filtered.length === 0) {
        emptyState.classList.remove('hidden');
    } else {
        emptyState.classList.add('hidden');
        filtered.forEach((student) => {
            const row = document.createElement('tr');
            row.className = "text-sm text-slate-700 dark:text-slate-300 transition-colors hover:bg-slate-50/50 dark:hover:bg-slate-800/30";
            row.innerHTML = `
                <td class="py-4 px-6 font-mono font-bold text-slate-400 text-xs">${student.id}</td>
                <td class="py-4 px-6">
                    <div class="font-bold text-slate-800 dark:text-slate-100">${student.name}</div>
                    <div class="text-xs text-slate-400">${student.email}</div>
                </td>
                <td class="py-4 px-6 font-medium text-slate-500 dark:text-slate-400">${student.major}</td>
                <td class="py-4 px-6">
                    <span class="font-bold text-brand-600 dark:text-brand-400">${student.gpa.toFixed(2)}</span>
                </td>
                <td class="py-4 px-6">
                    <div class="flex items-center gap-2">
                        <div class="w-16 bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                            <div class="h-full bg-emerald-500 rounded-full" style="width: ${student.attendance}%"></div>
                        </div>
                        <span class="font-bold text-xs">${student.attendance}%</span>
                    </div>
                </td>
                <td class="py-4 px-6 text-center">
                    <div class="flex items-center justify-center gap-2">
                        <button onclick="editStudent('${student.id}')" class="p-2 hover:bg-indigo-50 dark:hover:bg-indigo-950/50 hover:text-indigo-600 dark:hover:text-indigo-400 rounded-lg transition-colors" title="Edit Student">
                            <i class="fa-solid fa-pen text-sm"></i>
                        </button>
                        <button onclick="deleteStudent('${student.id}')" class="p-2 hover:bg-red-50 dark:hover:bg-red-950/50 hover:text-red-600 dark:hover:text-red-400 rounded-lg transition-colors" title="Delete Student">
                            <i class="fa-solid fa-trash-can text-sm"></i>
                        </button>
                    </div>
                </td>
            `;
            tableBody.appendChild(row);
        });
    }
}

// Live search binds
searchInput.addEventListener('input', renderStudents);
globalSearch.addEventListener('input', (e) => {
    searchInput.value = e.target.value;
    switchView('students');
    renderStudents();
});
filterMajor.addEventListener('change', renderStudents);

// Handle Student submission
document.getElementById('btn-add-student').addEventListener('click', () => {
    document.getElementById('student-form').reset();
    document.getElementById('student-index').value = '';
    document.getElementById('student-modal-title').textContent = "Add New Scholar";
    toggleModal('student-modal', true);
});

document.getElementById('student-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const index = document.getElementById('student-index').value;
    const name = document.getElementById('stud-name').value;
    const email = document.getElementById('stud-email').value;
    const major = document.getElementById('stud-major').value;
    const gpa = parseFloat(document.getElementById('stud-gpa').value);
    const attendance = parseInt(document.getElementById('stud-attendance').value);

    if (index === '') {
        // Create mode
        const generatedId = "SCH-" + Math.floor(10000 + Math.random() * 90000);
        state.students.push({ id: generatedId, name, email, major, gpa, attendance });
        state.addLog(`Created student record: ${name} (${generatedId})`);
    } else {
        // Edit mode
        const studentIndex = state.students.findIndex(s => s.id === index);
        if (studentIndex !== -1) {
            state.students[studentIndex] = { id: index, name, email, major, gpa, attendance };
            state.addLog(`Updated student record: ${name} (${index})`);
        }
    }
    state.save();
    toggleModal('student-modal', false);
    renderStudents();
});

window.editStudent = function(studentId) {
    const student = state.students.find(s => s.id === studentId);
    if (!student) return;

    document.getElementById('student-index').value = student.id;
    document.getElementById('stud-name').value = student.name;
    document.getElementById('stud-email').value = student.email;
    document.getElementById('stud-major').value = student.major;
    document.getElementById('stud-gpa').value = student.gpa;
    document.getElementById('stud-attendance').value = student.attendance;

    document.getElementById('student-modal-title').textContent = "Modify Scholar Record";
    toggleModal('student-modal', true);
}

window.deleteStudent = function(studentId) {
    if (confirm("Are you sure you want to scrub this student from the active database?")) {
        const studentName = state.students.find(s => s.id === studentId)?.name;
        state.students = state.students.filter(s => s.id !== studentId);
        state.addLog(`Deleted student record: ${studentName || studentId}`);
        state.save();
        renderStudents();
    }
}

// ======================= LECTURE PORTAL SYSTEM =======================
function renderLectures() {
    const grid = document.getElementById('lecture-cards-grid');
    grid.innerHTML = '';

    state.lectures.forEach(lec => {
        const div = document.createElement('div');
        div.className = "bg-white dark:bg-slate-900 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-800 overflow-hidden flex flex-col hover:shadow-md transition-shadow duration-300 card-shine";
        div.innerHTML = `
            <div class="p-6 flex-1 space-y-4">
                <div class="flex items-center justify-between">
                    <span class="px-2.5 py-1 text-xs font-bold uppercase rounded-lg bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-900/40">${lec.code}</span>
                    <span class="text-xs text-slate-400 font-semibold"><i class="fa-solid fa-hashtag mr-1"></i>${lec.id}</span>
                </div>
                <div>
                    <h4 class="text-base font-extrabold text-slate-800 dark:text-slate-100 line-clamp-1">${lec.title}</h4>
                    <p class="text-xs text-slate-400 mt-1"><i class="fa-solid fa-user-tie mr-1.5"></i>${lec.professor}</p>
                </div>
                <div class="grid grid-cols-2 gap-4 pt-3 border-t border-slate-100 dark:border-slate-800/80 text-xs text-slate-500 dark:text-slate-400">
                    <div>
                        <span class="block text-slate-400 font-semibold uppercase text-[10px]">Date & Time</span>
                        <span class="font-medium text-slate-700 dark:text-slate-300">${lec.date} • ${lec.time}</span>
                    </div>
                    <div>
                        <span class="block text-slate-400 font-semibold uppercase text-[10px]">Location</span>
                        <span class="font-medium text-slate-700 dark:text-slate-300 truncate block">${lec.location}</span>
                    </div>
                </div>
            </div>
            <div class="px-6 py-4 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
                <span class="text-xs text-slate-500 dark:text-slate-400 font-semibold"><i class="fa-solid fa-users mr-1.5"></i>${lec.attendees.length} Checked In</span>
                <button onclick="launchLecturePanel('${lec.id}')" class="px-4 py-2 bg-slate-900 dark:bg-slate-800 text-white rounded-xl text-xs font-bold hover:bg-brand-600 dark:hover:bg-brand-600 transition-colors flex items-center gap-1.5">
                    Launch Hub <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
                </button>
            </div>
        `;
        grid.appendChild(div);
    });
}

// Create Lecture
document.getElementById('btn-add-lecture').addEventListener('click', () => {
    document.getElementById('lecture-form').reset();
    toggleModal('lecture-modal', true);
});

document.getElementById('lecture-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const title = document.getElementById('lec-title').value;
    const code = document.getElementById('lec-code').value;
    const professor = document.getElementById('lec-prof').value;
    const date = document.getElementById('lec-date').value;
    const time = document.getElementById('lec-time').value;
    const location = document.getElementById('lec-location').value;

    const generatedId = "LEC-" + Math.floor(300 + Math.random() * 699);
    state.lectures.push({ id: generatedId, code, title, professor, date, time, location, attendees: [] });
    state.addLog(`Scheduled lecture session: ${title} [${code}]`);
    state.save();
    toggleModal('lecture-modal', false);
    renderLectures();
});

// Lecture checklist interactive session modal
window.launchLecturePanel = function(lectureId) {
    const lecture = state.lectures.find(l => l.id === lectureId);
    if (!lecture) return;

    state.activeLectureId = lectureId;
    document.getElementById('att-modal-title').textContent = lecture.title;
    document.getElementById('att-modal-subtitle').textContent = `${lecture.code} • ${lecture.professor}`;

    const checklist = document.getElementById('attendance-checklist');
    checklist.innerHTML = '';

    state.students.forEach(student => {
        const hasAttended = lecture.attendees.includes(student.id);
        const div = document.createElement('div');
        div.className = "flex items-center justify-between p-2.5 hover:bg-slate-50 dark:hover:bg-slate-800 rounded-xl transition-colors duration-150 border border-slate-100 dark:border-slate-800";
        div.innerHTML = `
            <div class="flex items-center gap-3">
                <input type="checkbox" id="chk-${student.id}" value="${student.id}" ${hasAttended ? 'checked' : ''} class="w-4.5 h-4.5 text-brand-600 bg-gray-100 border-gray-300 rounded focus:ring-brand-500 focus:ring-2">
                <label for="chk-${student.id}" class="text-sm font-semibold text-slate-700 dark:text-slate-300 cursor-pointer">
                    ${student.name}
                </label>
            </div>
            <span class="text-xs font-mono text-slate-400 font-bold">${student.id}</span>
        `;
        checklist.appendChild(div);
    });

    toggleModal('attendance-modal', true);
}

// Save dynamic attendance session
document.getElementById('save-attendance-btn').addEventListener('click', () => {
    const lecture = state.lectures.find(l => l.id === state.activeLectureId);
    if (!lecture) return;

    const checklist = document.getElementById('attendance-checklist');
    const checkedIds = Array.from(checklist.querySelectorAll('input[type="checkbox"]:checked')).map(el => el.value);

    // Update attendance list in lecture record
    lecture.attendees = checkedIds;
    state.addLog(`Updated live checklist for session ID: ${lecture.id}`);

    // Recalculate dynamic overall attendance metric for students in database based on historical records
    state.students.forEach(student => {
        const lecturesScheduledForMajor = state.lectures; // Simple prototype architecture maps to global scheduled lectures
        const attendedLecturesCount = state.lectures.filter(l => l.attendees.includes(student.id)).length;
        const finalAttendancePercent = lecturesScheduledForMajor.length > 0 
            ? Math.round((attendedLecturesCount / lecturesScheduledForMajor.length) * 100) 
            : student.attendance; // Fallback
        student.attendance = finalAttendancePercent;
    });

    state.save();
    toggleModal('attendance-modal', false);
    renderLectures();
});

// ======================= ANALYTICS ENGINE =======================
let gpaChart = null;
let attChart = null;

function renderAnalytics() {
    // Admin log tracker component
    const logsContainer = document.getElementById('admin-logs');
    logsContainer.innerHTML = '';
    state.logs.forEach(log => {
        const div = document.createElement('div');
        div.className = "flex items-start justify-between p-3 bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-xl text-xs gap-4";
        div.innerHTML = `
            <span class="font-mono font-bold text-indigo-500">${log.timestamp}</span>
            <span class="flex-1 font-medium text-slate-700 dark:text-slate-300">${log.action}</span>
            <span class="px-1.5 py-0.5 text-[10px] bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 font-bold rounded">SUCCESS</span>
        `;
        logsContainer.appendChild(div);
    });

    // Destroy existing charts to reload clean Canvas data
    if (gpaChart) gpaChart.destroy();
    if (attChart) attChart.destroy();

    const isDark = document.documentElement.classList.contains('dark');
    const textColor = isDark ? '#94a3b8' : '#64748b';
    const gridColor = isDark ? '#334155' : '#e2e8f0';

    // Chart 1: GPA distribution
    const ctxGpa = document.getElementById('gpaDistributionChart').getContext('2d');
    const gpaIntervals = { '3.5 - 4.0': 0, '3.0 - 3.49': 0, '2.5 - 2.99': 0, 'Under 2.5': 0 };
    
    state.students.forEach(s => {
        if (s.gpa >= 3.5) gpaIntervals['3.5 - 4.0']++;
        else if (s.gpa >= 3.0) gpaIntervals['3.0 - 3.49']++;
        else if (s.gpa >= 2.5) gpaIntervals['2.5 - 2.99']++;
        else gpaIntervals['Under 2.5']++;
    });

    gpaChart = new Chart(ctxGpa, {
        type: 'pie',
        data: {
            labels: Object.keys(gpaIntervals),
            datasets: [{
                data: Object.values(gpaIntervals),
                backgroundColor: ['#6366f1', '#38bdf8', '#fbbf24', '#f87171'],
                borderWidth: isDark ? 2 : 1,
                borderColor: isDark ? '#1e293b' : '#ffffff'
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: textColor }
                }
            }
        }
    });

    // Chart 2: Major Average attendance bar chart
    const ctxAtt = document.getElementById('attendanceChart').getContext('2d');
    const majorAttendance = {};
    const majorCount = {};

    state.students.forEach(s => {
        if (!majorAttendance[s.major]) {
            majorAttendance[s.major] = 0;
            majorCount[s.major] = 0;
        }
        majorAttendance[s.major] += s.attendance;
        majorCount[s.major]++;
    });

    const majors = Object.keys(majorAttendance);
    const avgAttendanceData = majors.map(m => Math.round(majorAttendance[m] / majorCount[m]));

    attChart = new Chart(ctxAtt, {
        type: 'bar',
        data: {
            labels: majors,
            datasets: [{
                label: 'Avg Attendance %',
                data: avgAttendanceData,
                backgroundColor: 'rgba(99, 102, 241, 0.85)',
                hoverBackgroundColor: 'rgba(99, 102, 241, 1)',
                borderRadius: 8
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    grid: { color: gridColor },
                    ticks: { color: textColor },
                    max: 100
                },
                x: {
                    grid: { display: false },
                    ticks: { color: textColor }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

// Initialize Application Engine on load
window.addEventListener('DOMContentLoaded', () => {
    switchView('dashboard');
});
