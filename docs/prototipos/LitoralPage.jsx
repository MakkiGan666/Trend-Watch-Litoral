import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Menu,
  X,
  Search,
  Bell,
  User,
  Home,
  TrendingUp,
  Newspaper,
  MessageSquare,
  MapPin,
  Filter,
  ChevronRight,
  Settings,
  Map,
  Zap,
  Eye,
  MessageCircle,
  Send,
  ThumbsUp,
  ThumbsDown,
  Minus,
} from 'lucide-react';

// ============================================================================
// MOCK DATA
// ============================================================================

const DEPARTMENTS = [
  {
    id: 'capital',
    name: 'Capital',
    mentions: 324,
    trend: 18.4,
    sentiment: { positive: 54, neutral: 31, negative: 15 },
  },
  {
    id: 'obera',
    name: 'Oberá',
    mentions: 287,
    trend: 12.1,
    sentiment: { positive: 61, neutral: 25, negative: 14 },
  },
  {
    id: 'iguazu',
    name: 'Iguazú',
    mentions: 412,
    trend: 28.5,
    sentiment: { positive: 68, neutral: 22, negative: 10 },
  },
  {
    id: 'eldorado',
    name: 'Eldorado',
    mentions: 198,
    trend: 5.2,
    sentiment: { positive: 52, neutral: 33, negative: 15 },
  },
  {
    id: 'sanignacio',
    name: 'San Ignacio',
    mentions: 156,
    trend: -3.1,
    sentiment: { positive: 48, neutral: 38, negative: 14 },
  },
  {
    id: 'cainguas',
    name: 'Cainguás',
    mentions: 89,
    trend: 2.3,
    sentiment: { positive: 55, neutral: 30, negative: 15 },
  },
  {
    id: 'libertador',
    name: 'Libertador General San Martín',
    mentions: 201,
    trend: 11.7,
    sentiment: { positive: 59, neutral: 28, negative: 13 },
  },
  {
    id: 'apostoles',
    name: 'Apóstoles',
    mentions: 143,
    trend: 7.4,
    sentiment: { positive: 56, neutral: 29, negative: 15 },
  },
  {
    id: 'belgrano',
    name: 'General Manuel Belgrano',
    mentions: 167,
    trend: 9.8,
    sentiment: { positive: 53, neutral: 32, negative: 15 },
  },
  {
    id: 'montecarlo',
    name: 'Montecarlo',
    mentions: 234,
    trend: 15.3,
    sentiment: { positive: 60, neutral: 26, negative: 14 },
  },
  {
    id: 'candelaria',
    name: 'Candelaria',
    mentions: 112,
    trend: 4.6,
    sentiment: { positive: 51, neutral: 34, negative: 15 },
  },
  {
    id: 'sanpedro',
    name: 'San Pedro',
    mentions: 178,
    trend: 8.9,
    sentiment: { positive: 57, neutral: 27, negative: 16 },
  },
  {
    id: 'sanjavier',
    name: 'San Javier',
    mentions: 145,
    trend: 6.2,
    sentiment: { positive: 54, neutral: 31, negative: 15 },
  },
  {
    id: 'concepcion',
    name: 'Concepción',
    mentions: 98,
    trend: 1.4,
    sentiment: { positive: 49, neutral: 36, negative: 15 },
  },
  {
    id: '25mayo',
    name: '25 de Mayo',
    mentions: 134,
    trend: 3.8,
    sentiment: { positive: 52, neutral: 33, negative: 15 },
  },
  {
    id: 'leandro',
    name: 'Leandro N. Alem',
    mentions: 156,
    trend: 6.9,
    sentiment: { positive: 55, neutral: 30, negative: 15 },
  },
  {
    id: 'guarani',
    name: 'Guaraní',
    mentions: 189,
    trend: 10.1,
    sentiment: { positive: 58, neutral: 28, negative: 14 },
  },
];

const DEPARTMENT_IMAGES = {
  capital: 'https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=900',
  obera: 'https://images.unsplash.com/photo-1500534623283-312aade485b7?w=900',
  iguazu: 'https://images.unsplash.com/photo-1544550285-f813152fb2fd?w=900',
  eldorado: 'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=900',
  sanignacio: 'https://images.unsplash.com/photo-1500534623283-312aade485b7?w=900',
  cainguas: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=900',
  libertador: 'https://images.unsplash.com/photo-1500534623283-312aade485b7?w=900',
  apostoles: 'https://images.unsplash.com/photo-1500534623283-312aade485b7?w=900',
  belgrano: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=900',
  montecarlo: 'https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=900',
  candelaria: 'https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=900',
  sanpedro: 'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=900',
  sanjavier: 'https://images.unsplash.com/photo-1500534623283-312aade485b7?w=900',
  concepcion: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=900',
  '25mayo': 'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=900',
  leandro: 'https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=900',
  guarani: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=900',
};

const DEPARTMENT_LAYOUT = {
  capital: 'xl:col-start-1 xl:row-start-5',
  candelaria: 'xl:col-start-2 xl:row-start-5',
  apostoles: 'xl:col-start-3 xl:row-start-5',
  sanjavier: 'xl:col-start-4 xl:row-start-5',
  concepcion: 'xl:col-start-5 xl:row-start-5',
  leandro: 'xl:col-start-2 xl:row-start-4',
  '25mayo': 'xl:col-start-3 xl:row-start-4',
  obera: 'xl:col-start-4 xl:row-start-4',
  cainguas: 'xl:col-start-5 xl:row-start-4',
  sanignacio: 'xl:col-start-2 xl:row-start-3',
  montecarlo: 'xl:col-start-3 xl:row-start-3',
  libertador: 'xl:col-start-4 xl:row-start-3',
  eldorado: 'xl:col-start-5 xl:row-start-3',
  guarani: 'xl:col-start-6 xl:row-start-3',
  sanpedro: 'xl:col-start-3 xl:row-start-2',
  belgrano: 'xl:col-start-4 xl:row-start-2',
  iguazu: 'xl:col-start-5 xl:row-start-1',
};

const CATEGORIES = [
  'Salud',
  'Policiales',
  'Turismo',
  'Economía',
  'Política',
  'Educación',
  'Tecnología',
  'Sociedad',
  'Cultura',
  'Ambiente',
  'Deportes',
  'Festividades',
];

const SOURCES = ['Noticias', 'Redes sociales', 'Medios locales', 'RSS'];

const NEWS = [
  {
    id: 1,
    title: 'Posadas registra aumento de visitantes en temporada alta',
    department: 'Capital',
    category: 'Turismo',
    date: '2024-01-15T14:30:00',
    source: 'Noticias',
    trend: 34,
    sentiment: 'positive',
    mentions: 342,
    image: 'https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=400',
    summary: 'Los números de turismo en Posadas muestran un crecimiento sostenido durante los últimos meses, con un incremento del 34% respecto al período anterior.',
    relevance: 92,
  },
  {
    id: 2,
    title: 'Iniciativa educativa en Oberá busca mejorar acceso tecnológico',
    department: 'Oberá',
    category: 'Educación',
    date: '2024-01-15T12:00:00',
    source: 'Medios locales',
    trend: 18,
    sentiment: 'positive',
    mentions: 187,
    image: 'https://images.unsplash.com/photo-1427504494785-cdec37e4af7f?w=400',
    summary: 'Se inicia programa de capacitación en tecnología para estudiantes de escuelas públicas en la región.',
    relevance: 78,
  },
  {
    id: 3,
    title: 'Iguazú: Parque Nacional genera economía para la región',
    department: 'Iguazú',
    category: 'Economía',
    date: '2024-01-14T09:15:00',
    source: 'Noticias',
    trend: 42,
    sentiment: 'positive',
    mentions: 523,
    image: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=400',
    summary: 'El Parque Nacional Iguazú continúa siendo motor económico generando empleo y turismo en la provincia.',
    relevance: 95,
  },
  {
    id: 4,
    title: 'Actividades culturales en Montecarlo atraen a visitantes',
    department: 'Montecarlo',
    category: 'Cultura',
    date: '2024-01-14T16:45:00',
    source: 'Redes sociales',
    trend: 28,
    sentiment: 'positive',
    mentions: 298,
    image: 'https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=400',
    summary: 'Festival cultural en Montecarlo congrega a artistas locales y atrae visitantes de toda la provincia.',
    relevance: 85,
  },
  {
    id: 5,
    title: 'Eldorado impulsa proyectos de sustentabilidad ambiental',
    department: 'Eldorado',
    category: 'Ambiente',
    date: '2024-01-13T11:20:00',
    source: 'Medios locales',
    trend: 12,
    sentiment: 'positive',
    mentions: 156,
    image: 'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=400',
    summary: 'Nuevas iniciativas ecológicas en Eldorado buscan proteger la biodiversidad de la región.',
    relevance: 71,
  },
  {
    id: 6,
    title: 'Evento deportivo regional en Oberá convoca participantes',
    department: 'Oberá',
    category: 'Deportes',
    date: '2024-01-13T14:00:00',
    source: 'Redes sociales',
    trend: 22,
    sentiment: 'positive',
    mentions: 201,
    image: 'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=400',
    summary: 'Competencias deportivas atraen atletas de toda la región en fin de semana intenso.',
    relevance: 68,
  },
];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1, delayChildren: 0.2 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

// ============================================================================
// COMPONENTES INTERNOS
// ============================================================================

function Navbar({ onMenuToggle, isMobileMenuOpen }) {
  return (
    <motion.nav
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="fixed top-0 left-0 right-0 z-40 backdrop-blur-md bg-[#051F20]/80 border-b border-[#8EB69B]/30"
    >
      <div className="flex items-center justify-between px-4 sm:px-6 py-3">
        <div className="flex items-center gap-2 sm:gap-4">
          <a
            href="#litoral-map"
            className="hidden sm:inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-[#DAF1DE] hover:bg-[#163832]/80 border border-[#8EB69B]/30 transition"
          >
            <MapPin size={16} className="text-[#8EB69B]" />
            Litoral
          </a>
          <button
            onClick={onMenuToggle}
            className="md:hidden p-2 hover:bg-[#163832]/70 rounded-lg transition"
            aria-label="Toggle menu"
          >
            {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-[#8EB69B] to-[#DAF1DE] rounded-lg flex items-center justify-center">
              <TrendingUp size={18} className="text-[#051F20]" />
            </div>
            <h1 className="text-[#DAF1DE] font-bold hidden sm:block">TrendWatch</h1>
          </div>
        </div>

        <div className="flex-1 max-w-xs sm:max-w-md mx-2 sm:mx-4">
          <div className="relative">
            <Search
              size={18}
              className="absolute left-3 top-1/2 transform -translate-y-1/2 text-[#8EB69B]/70"
            />
            <input
              type="text"
              placeholder="Buscar..."
              className="w-full pl-10 pr-4 py-2 rounded-full bg-[#163832]/80 backdrop-blur border border-[#8EB69B]/30 text-[#DAF1DE] placeholder-[#8EB69B]/70 focus:outline-none focus:border-[#8EB69B]/60 transition text-sm"
            />
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-4">
          <button
            className="p-2 hover:bg-[#163832]/50 rounded-lg transition hidden sm:block"
            aria-label="Notifications"
          >
            <Bell size={20} className="text-[#8EB69B]" />
          </button>
          <button className="w-8 h-8 sm:w-10 sm:h-10 bg-[#8EB69B] rounded-full flex items-center justify-center text-[#051F20] font-bold hover:opacity-90 transition">
            SB
          </button>
        </div>
      </div>
    </motion.nav>
  );
}

function Sidebar({ isOpen, onClose }) {
  const menuItems = [
    { icon: Home, label: 'Inicio', section: 'inicio' },
    { icon: TrendingUp, label: 'Tendencias', section: 'tendencias' },
    { icon: Newspaper, label: 'Noticias', section: 'noticias' },
    { icon: MessageSquare, label: 'Menciones', section: 'menciones' },
  ];

  const segmentation = [
    { icon: Filter, label: 'Categorías' },
    { icon: MapPin, label: 'Localidades' },
    { icon: Zap, label: 'Fuentes' },
    { icon: Eye, label: 'Análisis' },
  ];

  return (
    <>
      {/* Mobile overlay */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/50 z-30 md:hidden"
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <motion.aside
        initial={{ x: -300 }}
        animate={{ x: 0 }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        className={`fixed md:relative md:translate-x-0 w-64 h-screen z-30 backdrop-blur-md bg-[#0B2B26]/90 border-r border-[#8EB69B]/30 p-6 flex flex-col overflow-y-auto ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 bg-gradient-to-br from-[#8EB69B] to-[#DAF1DE] rounded-lg flex items-center justify-center">
            <TrendingUp size={20} className="text-[#051F20]" />
          </div>
          <div>
            <h2 className="text-[#DAF1DE] font-bold text-sm">TrendWatch</h2>
            <p className="text-[#8EB69B] text-xs">Litoral</p>
          </div>
        </div>

        <nav className="space-y-2 mb-8 flex-1">
          <p className="text-[#8EB69B]/60 text-xs font-semibold uppercase px-3 mb-4">
            Explorar
          </p>
          {menuItems.map((item) => (
            <button
              key={item.section}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[#163832]/30 transition text-[#DAF1DE] hover:text-[#8EB69B] group"
            >
              <item.icon size={18} className="group-hover:text-[#8EB69B]" />
              <span className="text-sm">{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="mb-8">
          <p className="text-[#8EB69B]/60 text-xs font-semibold uppercase px-3 mb-4">
            Segmentación
          </p>
          <div className="space-y-2">
            {segmentation.map((item) => (
              <button
                key={item.label}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[#163832]/50 transition text-[#DAF1DE] hover:text-[#8EB69B] group"
              >
                <item.icon size={16} />
                <span className="text-sm">{item.label}</span>
              </button>
            ))}
          </div>
        </div>

        <button className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[#163832]/30 transition text-[#8EB69B] w-full">
          <Settings size={18} />
          <span className="text-sm">Configuración</span>
        </button>
      </motion.aside>
    </>
  );
}

function MapaMisiones({ activeDepartment, onDepartmentSelect }) {
  const mapPositions = {
    capital: { x: 55, y: 65 },
    obera: { x: 50, y: 45 },
    iguazu: { x: 40, y: 15 },
    eldorado: { x: 65, y: 50 },
    sanignacio: { x: 35, y: 35 },
    cainguas: { x: 60, y: 70 },
    libertador: { x: 45, y: 55 },
    apostoles: { x: 50, y: 70 },
    belgrano: { x: 70, y: 60 },
    montecarlo: { x: 55, y: 50 },
    candelaria: { x: 65, y: 75 },
    sanpedro: { x: 30, y: 50 },
    sanjavier: { x: 25, y: 40 },
    concepcion: { x: 35, y: 60 },
    '25mayo': { x: 45, y: 75 },
    leandro: { x: 40, y: 85 },
    guarani: { x: 55, y: 85 },
  };

  return (
    <motion.div
      variants={itemVariants}
      className="backdrop-blur-md bg-[#163832]/30 border border-[#8EB69B]/20 rounded-3xl p-8 h-96 flex items-center justify-center overflow-hidden shadow-2xl"
    >
      <svg
        viewBox="0 0 100 100"
        className="w-full h-full"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M42 4 64 8 76 24 68 40 82 58 67 72 72 91 51 96 35 85 25 70 12 57 20 38 16 20Z"
          fill="#163832"
          fillOpacity=".8"
          stroke="#8EB69B"
          strokeWidth=".8"
          opacity=".95"
        />
        <path d="M25 70 51 60 67 72M20 38 42 44 68 40M35 85 45 72 51 60M42 4 42 44 25 70M64 8 51 60 72 91" fill="none" stroke="#8EB69B" strokeWidth=".35" opacity=".55" />

        {/* Departments as dots */}
        {DEPARTMENTS.map((dept) => {
          const pos = mapPositions[dept.id];
          const isActive = activeDepartment?.id === dept.id;

          return (
            <g key={dept.id}>
              <motion.circle
                cx={pos.x}
                cy={pos.y}
                r={isActive ? 3.5 : 2.5}
                fill={isActive ? '#8EB69B' : '#DAF1DE'}
                opacity={isActive ? 1 : 0.6}
                className="cursor-pointer hover:opacity-100 transition"
                whileHover={{ r: 3.5 }}
                whileTap={{ scale: 1.1 }}
                onClick={() => onDepartmentSelect(dept)}
                filter={isActive ? 'drop-shadow(0 0 3px #8EB69B)' : 'none'}
                style={{ cursor: 'pointer' }}
              />
              {isActive && (
                <motion.circle
                  cx={pos.x}
                  cy={pos.y}
                  r={5}
                  fill="none"
                  stroke="#8EB69B"
                  strokeWidth="0.3"
                  opacity="0.3"
                  animate={{ r: 7 }}
                  transition={{ duration: 1.5, repeat: Infinity }}
                />
              )}
            </g>
          );
        })}
      </svg>
    </motion.div>
  );
}

function DepartmentGrid({ activeDepartment, onDepartmentOpen }) {
  return (
    <motion.div
      variants={containerVariants}
      className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-6 xl:auto-rows-[9.5rem] gap-4"
    >
      {DEPARTMENTS.map((department) => {
        const isActive = activeDepartment?.id === department.id;
        return (
          <motion.button
            key={department.id}
            variants={itemVariants}
            type="button"
            onClick={() => onDepartmentOpen(department)}
            className={`relative min-h-40 overflow-hidden rounded-3xl border text-left shadow-2xl transition ${DEPARTMENT_LAYOUT[department.id]} ${
              isActive
                ? 'border-[#8EB69B] ring-1 ring-[#8EB69B]/50'
                : 'border-[#8EB69B]/30 hover:border-[#8EB69B]/70'
            }`}
          >
            <img
              src={DEPARTMENT_IMAGES[department.id]}
              alt={`Paisaje representativo de ${department.name}`}
              className="absolute inset-0 h-full w-full object-cover"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-[#051F20] via-[#0B2B26]/75 to-[#163832]/25" />
            <div className="relative flex h-full flex-col justify-end p-4">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-wide text-[#8EB69B]">Departamento</p>
                  <h4 className="text-lg font-semibold text-[#DAF1DE]">{department.name}</h4>
                </div>
                <span className="text-sm font-semibold text-[#8EB69B]">{department.mentions} menciones</span>
              </div>
              <p className="mt-2 text-xs text-[#DAF1DE]/75">Ver noticias y comentarios</p>
            </div>
          </motion.button>
        );
      })}
    </motion.div>
  );
}

function DepartmentPanel({ department }) {
  if (!department) {
    return (
      <motion.div
        variants={itemVariants}
        className="backdrop-blur-md bg-[#163832]/80 border border-[#8EB69B]/30 rounded-3xl p-8 h-96 flex flex-col items-center justify-center text-center shadow-2xl"
      >
        <MapPin size={40} className="text-[#8EB69B]/50 mb-4" />
        <p className="text-[#8EB69B]/60">Selecciona un departamento</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      key={department.id}
      variants={itemVariants}
      className="relative overflow-hidden backdrop-blur-md bg-[#163832]/80 border border-[#8EB69B]/30 rounded-3xl p-8 h-96 flex flex-col shadow-2xl"
    >
      <img src={DEPARTMENT_IMAGES[department.id]} alt="" className="absolute inset-0 h-full w-full object-cover opacity-20" />
      <div className="absolute inset-0 bg-[#0B2B26]/75" />
      <div className="relative flex h-full flex-col">
      <motion.h3
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="text-2xl font-bold text-[#DAF1DE] mb-2"
      >
        {department.name}
      </motion.h3>

      <div className="flex items-baseline gap-2 mb-6">
        <p className="text-4xl font-bold text-[#8EB69B]">{department.mentions}</p>
        <p className="text-[#DAF1DE]">menciones</p>
        <span
          className={`text-lg font-semibold ml-auto ${
            department.trend >= 0 ? 'text-[#8EB69B]' : 'text-red-400'
          }`}
        >
          {department.trend > 0 ? '+' : ''}
          {department.trend}%
        </span>
      </div>

      <div className="space-y-3 flex-1">
        <p className="text-[#DAF1DE] text-sm font-semibold">Sentimiento</p>
        {[
          {
            label: 'Positivo',
            value: department.sentiment.positive,
            color: '#8EB69B',
          },
          {
            label: 'Neutral',
            value: department.sentiment.neutral,
            color: '#DAF1DE',
          },
          {
            label: 'Negativo',
            value: department.sentiment.negative,
            color: '#DAF1DE',
          },
        ].map((sentiment) => (
          <div key={sentiment.label}>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-[#DAF1DE]">{sentiment.label}</span>
              <span className="text-[#8EB69B]">{sentiment.value}%</span>
            </div>
            <div className="w-full bg-[#0B2B26]/50 rounded-full h-2">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${sentiment.value}%` }}
                transition={{ duration: 1, delay: 0.2 }}
                className="h-full rounded-full"
                style={{ backgroundColor: sentiment.color }}
              />
            </div>
          </div>
        ))}
      </div>

      <button className="w-full mt-4 py-2 bg-[#8EB69B]/20 hover:bg-[#8EB69B]/30 border border-[#8EB69B]/40 rounded-lg text-[#8EB69B] text-sm font-medium transition">
        Ver análisis completo
      </button>
      </div>
    </motion.div>
  );
}

function FilterBar({ filters, onFilterChange }) {
  return (
    <motion.div
      variants={itemVariants}
      className="backdrop-blur-md bg-[#163832]/30 border border-[#8EB69B]/20 rounded-3xl p-6 shadow-2xl"
    >
      <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 gap-4">
        {[
          {
            label: 'Categoría',
            key: 'category',
            options: CATEGORIES,
          },
          {
            label: 'Fuente',
            key: 'source',
            options: SOURCES,
          },
          {
            label: 'Período',
            key: 'period',
            options: ['Hoy', 'Últimos 7 días', 'Últimos 30 días'],
          },
          {
            label: 'Sentimiento',
            key: 'sentiment',
            options: ['Todos', 'Positivo', 'Neutral', 'Negativo'],
          },
        ].map((filter) => (
          <div key={filter.key}>
            <label className="text-[#8EB69B] text-xs font-semibold uppercase block mb-2">
              {filter.label}
            </label>
            <select
              value={filters[filter.key] || ''}
              onChange={(e) =>
                onFilterChange(filter.key, e.target.value)
              }
              className="w-full px-3 py-2 rounded-lg bg-[#0B2B26]/50 border border-[#8EB69B]/20 text-[#DAF1DE] text-sm focus:outline-none focus:border-[#8EB69B]/50 transition"
            >
              <option value="">Todos</option>
              {filter.options.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

function NewsCard({ news, onClick }) {
  const sentimentColor = {
    positive: 'text-[#8EB69B]',
    neutral: 'text-[#DAF1DE]',
    negative: 'text-red-400',
  };

  const date = new Date(news.date);
  const now = new Date();
  const diffMinutes = Math.floor((now - date) / 60000);
  const timeAgo =
    diffMinutes < 60
      ? `Hace ${diffMinutes}m`
      : diffMinutes < 1440
      ? `Hace ${Math.floor(diffMinutes / 60)}h`
      : `Hace ${Math.floor(diffMinutes / 1440)}d`;

  return (
    <motion.button
      variants={itemVariants}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="text-left backdrop-blur-md bg-[#163832]/30 border border-[#8EB69B]/20 rounded-3xl overflow-hidden shadow-2xl hover:border-[#8EB69B]/50 transition group"
    >
      <div className="aspect-video bg-[#0B2B26]/50 overflow-hidden relative">
        <img
          src={news.image}
          alt={news.title}
          className="w-full h-full object-cover group-hover:scale-105 transition"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-[#051F20]/80 to-transparent" />
      </div>

      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <span className="text-xs px-2 py-1 rounded-full bg-[#8EB69B]/20 border border-[#8EB69B]/30 text-[#8EB69B]">
            {news.category}
          </span>
          <span className={`text-xs font-semibold ${sentimentColor[news.sentiment]}`}>
            {news.sentiment === 'positive'
              ? '+' + news.trend + '%'
              : news.sentiment === 'negative'
              ? '-' + news.trend + '%'
              : news.trend + '%'}
          </span>
        </div>

        <h4 className="font-bold text-[#DAF1DE] text-sm mb-2 line-clamp-2 group-hover:text-[#8EB69B] transition">
          {news.title}
        </h4>

        <div className="flex items-center justify-between text-xs text-[#DAF1DE]">
          <span>{news.department}</span>
          <span>{timeAgo}</span>
        </div>

        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-[#8EB69B]/10 text-[#8EB69B]/60 text-xs">
          <span className="flex items-center gap-1">
            <Eye size={14} />
            {news.mentions}
          </span>
          <span>{news.source}</span>
        </div>
      </div>
    </motion.button>
  );
}

function NewsModal({ news, isOpen, onClose, onAddComment }) {
  const [userSentiment, setUserSentiment] = useState(null);
  const [comments, setComments] = useState([
    {
      id: 1,
      author: 'María García',
      time: 'Hace 2h',
      text: 'Excelente noticia para el turismo de la región',
      sentiment: 'positive',
    },
    {
      id: 2,
      author: 'Juan López',
      time: 'Hace 1h',
      text: 'Se necesita más inversión en infraestructura',
      sentiment: 'neutral',
    },
  ]);
  const [newComment, setNewComment] = useState('');

  const handleAddComment = () => {
    if (newComment.trim()) {
      const comment = {
        id: comments.length + 1,
        author: 'SB',
        time: 'Ahora',
        text: newComment,
        sentiment: userSentiment || 'neutral',
      };
      setComments([...comments, comment]);
      setNewComment('');
    }
  };

  if (!isOpen || !news) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          onClick={(e) => e.stopPropagation()}
          className="backdrop-blur-md bg-[#163832]/80 border border-[#8EB69B]/30 rounded-3xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
        >
          {/* Cabecera */}
          <div className="relative aspect-video overflow-hidden">
            <img
              src={news.image}
              alt={news.title}
              className="w-full h-full object-cover"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-[#051F20] via-transparent to-transparent" />
            <button
              onClick={onClose}
              className="absolute top-4 right-4 p-2 bg-[#051F20]/50 hover:bg-[#051F20]/70 rounded-lg transition"
              aria-label="Close modal"
            >
              <X size={24} className="text-[#DAF1DE]" />
            </button>
          </div>

          <div className="p-6 sm:p-8">
            <div className="flex items-center justify-between gap-4 mb-4">
              <span className="text-xs px-3 py-1 rounded-full bg-[#8EB69B]/20 border border-[#8EB69B]/30 text-[#8EB69B]">
                {news.category}
              </span>
              <span className="text-xs text-[#DAF1DE]">{news.source}</span>
            </div>

            <h2 className="text-3xl font-bold text-[#DAF1DE] mb-4">{news.title}</h2>

            <div className="flex items-center gap-4 mb-6 text-sm text-[#DAF1DE]">
              <span>{news.department}</span>
              <span>•</span>
              <span>{new Date(news.date).toLocaleDateString('es-AR')}</span>
              <span>•</span>
              <span className="text-[#8EB69B]">Relevancia: {news.relevance}%</span>
            </div>

            <p className="text-[#DAF1DE] mb-8 leading-relaxed">
              {news.summary}
            </p>

            {/* Métricas */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8 p-4 bg-[#0B2B26]/30 rounded-lg">
              {[
                { label: 'Menciones', value: news.mentions },
                { label: 'Tendencia', value: (news.trend > 0 ? '+' : '') + news.trend + '%' },
                { label: 'Relevancia', value: news.relevance + '%' },
                {
                  label: 'Sentimiento',
                  value: news.sentiment.charAt(0).toUpperCase() + news.sentiment.slice(1),
                },
              ].map((metric) => (
                <div key={metric.label} className="text-center">
                  <p className="text-[#8EB69B]/60 text-xs uppercase">{metric.label}</p>
                  <p className="text-lg font-bold text-[#8EB69B]">{metric.value}</p>
                </div>
              ))}
            </div>

            {/* Votación de sentimiento */}
            <div className="mb-8">
              <p className="text-[#8EB69B] font-semibold mb-3 text-sm">
                ¿Cuál es tu sentimiento?
              </p>
              <div className="flex gap-3 mb-4">
                {[
                  { key: 'positive', icon: ThumbsUp, label: 'Positivo', color: '#8EB69B' },
                  { key: 'neutral', icon: Minus, label: 'Neutral', color: '#DAF1DE' },
                  { key: 'negative', icon: ThumbsDown, label: 'Negativo', color: '#EF4444' },
                ].map((option) => (
                  <button
                    key={option.key}
                    onClick={() => setUserSentiment(option.key)}
                    className={`flex-1 py-2 px-3 rounded-lg border transition flex items-center justify-center gap-2 text-sm`}
                    style={
                      userSentiment === option.key
                        ? {
                            backgroundColor: option.color + '20',
                            borderColor: option.color,
                            color: option.color,
                          }
                        : {
                            backgroundColor: '#0B2B2630',
                            borderColor: '#8EB69B33',
                            color: '#DAF1DE',
                          }
                    }
                  >
                    <option.icon size={16} />
                    <span className="hidden sm:inline">{option.label}</span>
                  </button>
                ))}
              </div>

              {/* Distribución de sentimientos */}
              <div className="space-y-2">
                {[
                  { label: 'Positivo', value: 54, color: '#8EB69B' },
                  { label: 'Neutral', value: 31, color: '#DAF1DE' },
                  { label: 'Negativo', value: 15, color: '#EF4444' },
                ].map((sentiment) => (
                  <div key={sentiment.label}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[#DAF1DE]">{sentiment.label}</span>
                      <span style={{ color: sentiment.color }}>{sentiment.value}%</span>
                    </div>
                    <div className="w-full bg-[#0B2B26]/50 rounded-full h-2">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: sentiment.value + '%',
                          backgroundColor: sentiment.color,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Comentarios */}
            <div className="border-t border-[#8EB69B]/20 pt-6">
              <p className="text-[#8EB69B] font-semibold mb-4 text-sm">
                Vista Comentarios ({comments.length})
              </p>

              <div className="space-y-4 mb-6 max-h-64 overflow-y-auto">
                {comments.map((comment) => (
                  <div key={comment.id} className="p-3 bg-[#0B2B26]/30 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-[#DAF1DE] font-semibold text-sm">
                        {comment.author}
                      </p>
                      <p className="text-[#8EB69B]/60 text-xs">{comment.time}</p>
                    </div>
                    <p className="text-[#DAF1DE] text-sm mb-2">{comment.text}</p>
                    <div
                      className="inline-block text-xs px-2 py-1 rounded"
                      style={{
                        backgroundColor:
                          comment.sentiment === 'positive'
                            ? '#8EB69B20'
                            : comment.sentiment === 'negative'
                            ? '#EF444420'
                            : '#DAF1DE20',
                        color:
                          comment.sentiment === 'positive'
                            ? '#8EB69B'
                            : comment.sentiment === 'negative'
                            ? '#EF4444'
                            : '#DAF1DE',
                      }}
                    >
                      {comment.sentiment}
                    </div>
                  </div>
                ))}
              </div>

              {/* Input de comentario */}
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Escribí tu comentario..."
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleAddComment()}
                  className="flex-1 px-4 py-2 rounded-lg bg-[#0B2B26]/50 border border-[#8EB69B]/20 text-[#DAF1DE] placeholder-[#8EB69B]/40 focus:outline-none focus:border-[#8EB69B]/50 transition text-sm"
                />
                <button
                  onClick={handleAddComment}
                  className="p-2 bg-[#8EB69B]/20 hover:bg-[#8EB69B]/30 border border-[#8EB69B]/40 rounded-lg text-[#8EB69B] transition"
                  aria-label="Send comment"
                >
                  <Send size={18} />
                </button>
              </div>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export default function LitoralPage() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [activeDepartment, setActiveDepartment] = useState(null);
  const [selectedNews, setSelectedNews] = useState(null);
  const [filters, setFilters] = useState({
    category: '',
    source: '',
    period: '',
    sentiment: '',
  });

  const filteredNews = useMemo(() => {
    return NEWS.filter((item) => {
      if (filters.category && item.category !== filters.category) return false;
      if (filters.source && item.source !== filters.source) return false;
      if (
        filters.sentiment &&
        filters.sentiment !== 'Todos' &&
        item.sentiment !==
          filters.sentiment.toLowerCase()
      )
        return false;
      return true;
    });
  }, [filters]);

  const handleFilterChange = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const handleDepartmentOpen = (department) => {
    setActiveDepartment(department);
    const departmentNews = NEWS.find((item) => item.department === department.name);
    setSelectedNews(
      departmentNews || {
        id: `department-${department.id}`,
        title: `Conversación pública en ${department.name}`,
        department: department.name,
        category: 'Noticias locales',
        date: new Date().toISOString(),
        source: 'TrendWatch Litoral',
        trend: department.trend,
        sentiment: 'neutral',
        mentions: department.mentions,
        image: DEPARTMENT_IMAGES[department.id],
        summary: `Explorá las menciones, noticias y opiniones recientes de ${department.name}.`,
        relevance: 80,
      },
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#051F20] via-[#0B2B26] to-[#051F20] text-[#DAF1DE] overflow-x-hidden">
      <Navbar
        onMenuToggle={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
        isMobileMenuOpen={isMobileMenuOpen}
      />

      <div className="flex pt-16">
        <Sidebar
          isOpen={isMobileMenuOpen}
          onClose={() => setIsMobileMenuOpen(false)}
        />

        <main className="flex-1 overflow-auto">
          <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            className="p-4 sm:p-6 max-w-7xl mx-auto space-y-8"
          >
            {/* Introducción */}
            <motion.section id="litoral-map" variants={itemVariants} className="mt-4 scroll-mt-24">
              <h2 className="text-4xl font-bold text-[#DAF1DE] mb-2">Litoral</h2>
              <p className="text-[#DAF1DE] text-lg">
                Explorá las tendencias y conversaciones que están ocurriendo en
                Misiones en tiempo real.
              </p>
            </motion.section>

            {/* Mapa y Panel */}
            <motion.div
              variants={itemVariants}
              className="grid grid-cols-1 lg:grid-cols-3 gap-6"
            >
              <div className="lg:col-span-2">
                <MapaMisiones
                  activeDepartment={activeDepartment}
                  onDepartmentSelect={setActiveDepartment}
                />
              </div>
              <div>
                <DepartmentPanel department={activeDepartment} />
              </div>
            </motion.div>

            <motion.section variants={itemVariants}>
              <div className="mb-5 flex items-end justify-between gap-4">
                <div>
                  <h3 className="text-2xl font-bold text-[#DAF1DE]">Departamentos de Misiones</h3>
                  <p className="mt-1 text-sm text-[#8EB69B]">Seleccioná una tarjeta para explorar sus noticias y comentarios.</p>
                </div>
                <span className="hidden sm:inline text-xs uppercase tracking-[.16em] text-[#8EB69B]/80">17 departamentos</span>
              </div>
              <DepartmentGrid
                activeDepartment={activeDepartment}
                onDepartmentOpen={handleDepartmentOpen}
              />
            </motion.section>

            {/* "Cómo funciona" */}
            <motion.section variants={itemVariants}>
              <h3 className="text-2xl font-bold text-[#DAF1DE] mb-6">
                Cómo funciona
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {[
                  {
                    step: '01',
                    title: 'Explora el mapa',
                    desc: 'Seleccioná un departamento de Misiones',
                    icon: Map,
                  },
                  {
                    step: '02',
                    title: 'Filtra tendencias',
                    desc: 'Explorá información por categoría, fuente y período',
                    icon: Filter,
                  },
                  {
                    step: '03',
                    title: 'Analiza',
                    desc: 'Consultá publicaciones, tendencias y sentimiento',
                    icon: Eye,
                  },
                ].map((item) => (
                  <motion.div
                    key={item.step}
                    variants={itemVariants}
                    className="backdrop-blur-md bg-[#163832]/30 border border-[#8EB69B]/20 rounded-3xl p-6 shadow-2xl hover:border-[#8EB69B]/50 transition"
                  >
                    <div className="flex items-start gap-4">
                      <div className="text-3xl font-bold text-[#8EB69B]/50">
                        {item.step}
                      </div>
                      <div className="flex-1">
                        <item.icon
                          size={24}
                          className="text-[#8EB69B] mb-2"
                        />
                        <h4 className="font-bold text-[#DAF1DE] mb-2">
                          {item.title}
                        </h4>
                        <p className="text-[#DAF1DE] text-sm">{item.desc}</p>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.section>

            {/* Filtros */}
            <motion.section variants={itemVariants}>
              <FilterBar filters={filters} onFilterChange={handleFilterChange} />
            </motion.section>

            {/* Noticias */}
            <motion.section variants={itemVariants}>
              <h3 className="text-2xl font-bold text-[#DAF1DE] mb-6">
                Noticias & Tendencias
              </h3>
              <motion.div
                className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6"
                variants={containerVariants}
              >
                {filteredNews.length > 0 ? (
                  filteredNews.map((news) => (
                    <NewsCard
                      key={news.id}
                      news={news}
                      onClick={() => setSelectedNews(news)}
                    />
                  ))
                ) : (
                  <div className="col-span-full text-center py-12">
                    <p className="text-[#8EB69B]/60">
                      No hay noticias con los filtros seleccionados
                    </p>
                  </div>
                )}
              </motion.div>
            </motion.section>
          </motion.div>
        </main>
      </div>

      <NewsModal
        news={selectedNews}
        isOpen={!!selectedNews}
        onClose={() => setSelectedNews(null)}
        onAddComment={() => {}}
      />
    </div>
  );
}

