#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <omp.h>

namespace md {
using Vec = std::array<double, 2>;
using Cell = std::array<int, 2>;
inline double norm2(const Vec& v) { return v[0]*v[0]+v[1]*v[1]; }
inline bool finite(const Vec& v) { return std::isfinite(v[0]) && std::isfinite(v[1]); }
inline void require(bool b, const std::string& s) { if (!b) throw std::runtime_error(s); }
inline std::string trim(std::string s) {
    const auto first=s.find_first_not_of(" \t\r\n");
    return first==std::string::npos ? "" : s.substr(first,s.find_last_not_of(" \t\r\n")-first+1);
}
inline std::string upper(std::string s) {
    for (char& c:s) c=static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return s;
}
template<class T> T number(const std::string& s) {
    std::istringstream in(s); T x{}; in>>x;
    require(!in.fail(), "Número inválido: " + s); in>>std::ws;
    require(in.eof(), "Número inválido: " + s); return x;
}
// Interação entre pares:
//   coulomb — repulsão 1/r com raio `cutoff` e `softening` (padrão, compatível com versões anteriores);
//   wca     — Lennard-Jones só repulsivo (Weeks–Chandler–Andersen), corte em 2^(1/6) sigma: "discos macios";
//   lj      — Lennard-Jones completo (repulsão + atração), corte em `lj_cutoff` * sigma, potencial deslocado;
//   none    — sem interação entre partículas.
enum class Potential { Coulomb, WCA, LJ, None };
inline Potential parse_potential(std::string s) {
    for(char& c:s) c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if(s=="coulomb") return Potential::Coulomb;
    if(s=="wca") return Potential::WCA;
    if(s=="lj" || s=="lennard-jones") return Potential::LJ;
    if(s=="none" || s=="nenhum") return Potential::None;
    throw std::runtime_error("potential deve ser coulomb, wca, lj ou none: "+s);
}
inline const char* potential_name(Potential p) {
    switch(p) { case Potential::Coulomb: return "coulomb"; case Potential::WCA: return "wca";
                case Potential::LJ: return "lj"; default: return "none"; }
}
struct Config {
    int particles=150, steps=5000, output_every=10, threads=4;
    double temperature=1, dt=0.001, cutoff=3, softening=0;
    double mass=1, charge=1, coulomb_constant=1, boltzmann=1;
    Potential potential=Potential::Coulomb;
    double sigma=0.2, epsilon=1, lj_cutoff=2.5;
    // Distância mínima entre partículas na condição inicial (0 = sorteio independente).
    double min_distance=0;
    // Passos de equilibração (com paredes temporárias na faixa inicial e reescala de T) antes de t = 0.
    int equilibration_steps=0;
    // Segunda espécie (B): quantidade, massa e diâmetro (negativo = igual à espécie A) e faixa inicial.
    int particles_b=0;
    double mass_b=-1, sigma_b=-1, initial_b_x_min=0, initial_b_x_max=1;
    // Distribuição inicial de velocidades: Maxwell–Boltzmann ou módulo único (direções aleatórias).
    bool monoenergetic=false;
    // Paredes externas: temperatura < 0 = reflexão especular; >= 0 = parede térmica (difusiva).
    // Ordem: esquerda, direita, inferior, superior.
    std::array<double,4> wall_temperature{-1,-1,-1,-1};
    // Pistão vertical: parte de piston_x0 e vai a piston_x1 (frações da largura) com
    // velocidade piston_speed > 0, a partir de t = piston_start. O gás fica à esquerda do pistão.
    double piston_x0=1, piston_x1=1, piston_speed=0, piston_start=0;
    bool has_piston() const { return piston_speed>0; }
    double mass_of_b() const { return mass_b>0 ? mass_b : mass; }
    double sigma_of_b() const { return sigma_b>0 ? sigma_b : sigma; }
    // Raio além do qual a força é zero.
    double interaction_radius() const {
        switch(potential) {
            case Potential::Coulomb: return cutoff;
            case Potential::WCA: return std::pow(2.0,1.0/6.0)*std::max(sigma,sigma_of_b());
            case Potential::LJ: return lj_cutoff*std::max(sigma,sigma_of_b());
            default: return cutoff;  // sem interação: só dimensiona a grade de vizinhos
        }
    }
    // Frações da largura da caixa ocupadas inicialmente; não são paredes.
    double initial_x_min=0, initial_x_max=1;
    std::uint64_t seed=42;
    std::filesystem::path geometry;
    void validate() const {
        require(particles>0 && particles<=10000000, "particles deve estar entre 1 e 10000000.");
        require(steps>=0 && steps<std::numeric_limits<int>::max(), "steps inválido.");
        require(output_every>0 && threads>=0, "output_every deve ser positivo; threads >= 0.");
        for (auto x:{temperature,dt,cutoff,softening,mass,charge,coulomb_constant,boltzmann,initial_x_min,initial_x_max,
                     sigma,epsilon,lj_cutoff,min_distance})
            require(std::isfinite(x), "Os parâmetros devem ser finitos.");
        require(temperature>=0 && dt>0 && cutoff>0 && softening>=0 && mass>0 && boltzmann>0 && coulomb_constant>=0,
                "T >= 0, dt/raio/massa/kB > 0, softening/kC >= 0 são obrigatórios.");
        require(equilibration_steps>=0, "equilibration_steps deve ser >= 0.");
        require(particles_b>=0 && particles_b<=10000000, "particles_b deve estar entre 0 e 10000000.");
        for(double x:{mass_b,sigma_b,initial_b_x_min,initial_b_x_max,piston_x0,piston_x1,piston_speed,piston_start})
            require(std::isfinite(x), "Os parâmetros devem ser finitos.");
        require(initial_b_x_min>=0 && initial_b_x_min<initial_b_x_max && initial_b_x_max<=1,
                "A região inicial da espécie B requer 0 <= initial_b_x_min < initial_b_x_max <= 1.");
        for(double t:wall_temperature) require(std::isfinite(t) && (t<0 || t>0),
                "Temperaturas de parede devem ser > 0 (ou omitidas para paredes especulares).");
        require(piston_speed>=0 && piston_start>=0, "piston_speed e piston_start devem ser >= 0.");
        if(has_piston()) require(piston_x0>0 && piston_x0<=1 && piston_x1>0 && piston_x1<=1,
                "piston_x0 e piston_x1 devem estar em (0, 1].");
        require(sigma>0 && epsilon>=0 && lj_cutoff>=1 && min_distance>=0,
                "sigma > 0, epsilon >= 0, lj_cutoff >= 1 e min_distance >= 0 são obrigatórios.");
        require(initial_x_min>=0 && initial_x_min<initial_x_max && initial_x_max<=1,
                "A região inicial requer 0 <= initial_x_min < initial_x_max <= 1.");
        require(!geometry.empty(), "Defina geometry no arquivo de parâmetros.");
        require(std::isfinite(boltzmann*temperature/mass) && std::isfinite(coulomb_constant*charge*charge)
                && std::isfinite(cutoff*cutoff) && cutoff*cutoff>0 && std::isfinite(softening*softening)
                && std::isfinite(cutoff*cutoff+softening*softening) && std::isfinite(dt*steps), "Escala numérica excessiva; use unidades reduzidas.");
    }
    static Config read(const std::filesystem::path& path) {
        std::ifstream in(path); require(bool(in), "Não foi possível abrir: "+path.u8string());
        Config c; std::set<std::string> seen; std::string line;
        while(std::getline(in,line)) {
            line=trim(line.substr(0,line.find('#'))); if(line.empty()) continue;
            auto eq=line.find('='); require(eq!=std::string::npos,"Esperado chave = valor: "+line);
            auto key=trim(line.substr(0,eq)), val=trim(line.substr(eq+1));
            require(!val.empty() && seen.insert(key).second,"Chave repetida ou valor vazio: "+key);
            if(key=="geometry") {
                if(val.size()>=2 && val.front()=='"' && val.back()=='"') val=val.substr(1,val.size()-2);
                c.geometry=std::filesystem::u8path(val);  // texto do .cfg em UTF-8
                if(c.geometry.is_relative()) c.geometry=path.parent_path()/c.geometry;
            }
            else if(key=="initial_x_min") c.initial_x_min=number<double>(val);
            else if(key=="initial_x_max") c.initial_x_max=number<double>(val);
            else if(key=="particles") c.particles=number<int>(val);
            else if(key=="steps") c.steps=number<int>(val);
            else if(key=="output_every") c.output_every=number<int>(val);
            else if(key=="threads") c.threads=number<int>(val);
            else if(key=="seed") { require(val.front()!='-',"seed deve ser >= 0."); c.seed=number<std::uint64_t>(val); }
            else if(key=="temperature") c.temperature=number<double>(val);
            else if(key=="dt") c.dt=number<double>(val);
            else if(key=="cutoff") c.cutoff=number<double>(val);
            else if(key=="softening") c.softening=number<double>(val);
            else if(key=="mass") c.mass=number<double>(val);
            else if(key=="charge") c.charge=number<double>(val);
            else if(key=="coulomb_constant") c.coulomb_constant=number<double>(val);
            else if(key=="boltzmann") c.boltzmann=number<double>(val);
            else if(key=="potential") c.potential=parse_potential(val);
            else if(key=="sigma") c.sigma=number<double>(val);
            else if(key=="epsilon") c.epsilon=number<double>(val);
            else if(key=="lj_cutoff") c.lj_cutoff=number<double>(val);
            else if(key=="min_distance") c.min_distance=number<double>(val);
            else if(key=="equilibration_steps") c.equilibration_steps=number<int>(val);
            else if(key=="particles_b") c.particles_b=number<int>(val);
            else if(key=="mass_b") c.mass_b=number<double>(val);
            else if(key=="sigma_b") c.sigma_b=number<double>(val);
            else if(key=="initial_b_x_min") c.initial_b_x_min=number<double>(val);
            else if(key=="initial_b_x_max") c.initial_b_x_max=number<double>(val);
            else if(key=="velocity_distribution") {
                auto v=val; for(char& ch:v) ch=static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
                require(v=="maxwell" || v=="mono","velocity_distribution deve ser maxwell ou mono.");
                c.monoenergetic=(v=="mono");
            }
            else if(key=="wall_temperature_left") c.wall_temperature[0]=number<double>(val);
            else if(key=="wall_temperature_right") c.wall_temperature[1]=number<double>(val);
            else if(key=="wall_temperature_bottom") c.wall_temperature[2]=number<double>(val);
            else if(key=="wall_temperature_top") c.wall_temperature[3]=number<double>(val);
            else if(key=="piston_x0") c.piston_x0=number<double>(val);
            else if(key=="piston_x1") c.piston_x1=number<double>(val);
            else if(key=="piston_speed") c.piston_speed=number<double>(val);
            else if(key=="piston_start") c.piston_start=number<double>(val);
            else throw std::runtime_error("Parâmetro desconhecido: "+key);
        }
        c.validate(); return c;
    }
};

// Máscara de células, índice x + nx*y. Fora do domínio é sólido.
struct Geometry {
    Cell dims{};
    Vec lower{}, spacing{};
    std::vector<unsigned char> fluid;
    std::size_t index(const Cell& c) const { return std::size_t(c[0])+std::size_t(dims[0])*c[1]; }
    bool is_fluid(const Cell& c) const {
        for(int a=0;a<2;++a) if(c[a]<0 || c[a]>=dims[a]) return false;
        return fluid[index(c)]!=0;
    }
    Cell cell(const Vec& p) const {
        Cell c{};
        for(int a=0;a<2;++a) {
            double x=std::floor((p[a]-lower[a])/spacing[a]);
            if(!std::isfinite(x) || x<0 || x>=dims[a]) return {-1,-1};
            c[a]=static_cast<int>(x);
        }
        return c;
    }
    Vec extent() const { return {dims[0]*spacing[0],dims[1]*spacing[1]}; }
    // Comprimento das superfícies sólidas (bordas da caixa e sólidos internos) em contato com o
    // fluido, contando só a parte com x < X (X = +inf: todas).
    double boundary_length(double X=std::numeric_limits<double>::infinity()) const {
        double total=0;
        for(int y=0;y<dims[1];++y) for(int x=0;x<dims[0];++x) if(is_fluid({x,y}))
            for(int a=0;a<2;++a) for(int s=-1;s<=1;s+=2) {
                Cell n{x,y}; n[a]+=s; if(is_fluid(n)) continue;
                const double x0=lower[0]+x*spacing[0];
                if(a==0) { if(x0+(s>0 ? spacing[0] : 0)<X) total+=spacing[1]; }
                else total+=std::clamp(X-x0,0.0,spacing[0]);
            }
        return total;
    }
    // Área livre com x < X.
    double free_area_left_of(double X) const {
        double total=0;
        for(int x=0;x<dims[0];++x) {
            const double x0=lower[0]+x*spacing[0], w=std::clamp(X-x0,0.0,spacing[0]);
            if(w<=0) break;
            int n=0; for(int y=0;y<dims[1];++y) n+=fluid[index({x,y})]!=0;
            total+=w*n*spacing[1];
        }
        return total;
    }
    static Geometry read(const std::filesystem::path& path) {
        std::ifstream in(path); require(bool(in),"Não foi possível abrir a geometria: "+path.u8string());
        std::string line;
        std::getline(in,line); require(upper(trim(line)).rfind("# VTK DATAFILE VERSION",0)==0,"Cabeçalho VTK inválido.");
        std::getline(in,line); std::getline(in,line);
        require(upper(trim(line))=="ASCII","Use VTK legacy ASCII; BINARY/XML não são suportados.");
        std::string key,kind;
        in>>key>>kind; require(upper(key)=="DATASET" && upper(kind)=="STRUCTURED_POINTS","Use DATASET STRUCTURED_POINTS.");
        Geometry g; bool have_dim=false,have_origin=false,have_spacing=false,have_data=false;
        std::size_t count=0; int nz=0; double origin_z=0,spacing_z=0;
        while(in>>key) {
            key=upper(key);
            if(key=="DIMENSIONS") { require(!have_dim,"DIMENSIONS repetido."); in>>g.dims[0]>>g.dims[1]>>nz; have_dim=true; }
            else if(key=="ORIGIN") { require(!have_origin,"ORIGIN repetido."); in>>g.lower[0]>>g.lower[1]>>origin_z; have_origin=true; }
            else if(key=="SPACING" || key=="ASPECT_RATIO") { require(!have_spacing,"SPACING repetido."); in>>g.spacing[0]>>g.spacing[1]>>spacing_z; have_spacing=true; }
            else if(key=="CELL_DATA" || key=="POINT_DATA") { in>>count; have_data=true; break; }
            else throw std::runtime_error("Campo de geometria VTK não suportado: "+key);
            require(bool(in),"Metadados VTK incompletos.");
        }
        require(have_dim && have_origin && have_spacing && have_data && bool(in),"Faltam DIMENSIONS, ORIGIN, SPACING ou dados no VTK.");
        require(nz==1,"A versão 2D requer DIMENSIONS nx ny 1 (plano xy).");
        require(std::isfinite(origin_z) && std::isfinite(spacing_z) && spacing_z>0,"ORIGIN/SPACING em z inválidos.");
        std::size_t expected=1;
        for(int a=0;a<2;++a) {
            require(g.dims[a]>0 && std::isfinite(g.lower[a]) && std::isfinite(g.spacing[a]) && g.spacing[a]>0,"Dimensões/origem/espaçamento VTK inválidos.");
            if(key=="CELL_DATA") { require(g.dims[a]>=2,"CELL_DATA 2D requer nx e ny >= 2; nz = 1."); --g.dims[a]; }
            else g.lower[a]-=0.5*g.spacing[a]; // Convenção: uma célula centrada em cada ponto.
            require(std::size_t(g.dims[a])<=100000000/expected,"Geometria excede 100 milhões de células.");
            expected*=g.dims[a];
            double high=g.lower[a]+g.dims[a]*g.spacing[a];
            require(std::isfinite(high) && high>g.lower[a] && g.lower[a]+g.spacing[a]>g.lower[a]
                    && high-g.spacing[a]<high,"Geometria fora da precisão numérica; reescale as coordenadas.");
        }
        require(count==expected,"Quantidade de valores VTK não corresponde às dimensões.");
        in>>key; require(upper(key)=="SCALARS","O primeiro atributo VTK deve ser SCALARS (máscara).");
        std::getline(in,line); std::istringstream scalar(line); std::string name,type,components,extra;
        require(bool(scalar>>name>>type),"SCALARS inválido.");
        if(scalar>>components) require(number<int>(components)==1,"A máscara SCALARS deve ter um componente.");
        require(!(scalar>>extra),"Declaração SCALARS inválida.");
        in>>key>>kind; require(upper(key)=="LOOKUP_TABLE","Falta LOOKUP_TABLE na máscara.");
        g.fluid.resize(count); std::size_t free=0;
        for(auto& value:g.fluid) { double x; require(bool(in>>x) && std::isfinite(x),"Máscara VTK incompleta ou inválida."); value=(x!=0); free+=value; }
        require(free>0,"A geometria não contém células livres (valores diferentes de zero).");
        return g;
    }

    // Percorre cada face atravessada (DDA): impede atravessar uma parede fina,
    // mesmo quando o deslocamento de um passo excede o tamanho de uma célula.
    bool drift(Vec& p, Vec& velocity, double dt) const {
        return drift(p,velocity,dt,[](int a,int,int,Vec& v) { v[a]=-v[a]; });
    }
    // bounce(eixo, sentido, parede, velocidade) decide a velocidade após a colisão.
    // parede: 0 esquerda, 1 direita, 2 inferior, 3 superior (bordas da caixa), 4 sólido interno.
    template<class Bounce>
    bool drift(Vec& p, Vec& velocity, double dt, Bounce&& bounce) const {
        if(!finite(p) || !finite(velocity)) return false;
        Cell c=cell(p); if(!is_fluid(c)) return false;
        double remaining=dt;
        for(int event=0;remaining>0 && event<100000;++event) {
            Vec times{},boundary{}; Cell sign{};
            for(int a=0;a<2;++a) {
                sign[a]=velocity[a]>0 ? 1 : (velocity[a]<0 ? -1 : 0);
                boundary[a]=lower[a]+(c[a]+(sign[a]>0 ? 1 : 0))*spacing[a];
                times[a]=sign[a] ? std::max(0.0,(boundary[a]-p[a])/velocity[a]) : std::numeric_limits<double>::infinity();
            }
            double hit=*std::min_element(times.begin(),times.end());
            if(hit>remaining) {
                for(int a=0;a<2;++a) p[a]+=velocity[a]*remaining;
                return finite(p) && is_fluid(cell(p));
            }
            for(int a=0;a<2;++a) p[a]+=velocity[a]*hit;
            remaining=std::max(0.0,remaining-hit);
            unsigned mask=0,blocked=0;
            for(int a=0;a<2;++a) if(std::abs(times[a]-hit)<=32*std::numeric_limits<double>::epsilon()*std::max(hit,1e-300)) mask|=1u<<a;
            // Em arestas/cantos, testa também os vizinhos diagonais. A regra
            // conservadora reflete os eixos que entram em qualquer célula sólida.
            for(unsigned subset=mask;subset;subset=(subset-1)&mask) {
                Cell neighbor=c; for(int a=0;a<2;++a) if(subset&(1u<<a)) neighbor[a]+=sign[a];
                if(!is_fluid(neighbor)) blocked|=subset;
            }
            for(int a=0;a<2;++a) if(mask&(1u<<a)) {
                if(blocked&(1u<<a)) {
                    Cell next=c; next[a]+=sign[a];
                    const int wall=next[a]<0 ? 2*a : (next[a]>=dims[a] ? 2*a+1 : 4);
                    bounce(a,sign[a],wall,velocity);
                }
                else c[a]+=sign[a];
                // Move alguns ULPs para o interior da célula de destino. O teste
                // de índice evita arredondamento de volta para a célula anterior.
                double center=lower[a]+(c[a]+0.5)*spacing[a];
                double nudge=std::min(0.25*spacing[a],32*std::numeric_limits<double>::epsilon()*std::max({std::abs(lower[a]),std::abs(boundary[a]),spacing[a]}));
                p[a]=std::nextafter(boundary[a]+std::copysign(nudge,center-boundary[a]),center);
                for(int n=0;n<16 && std::floor((p[a]-lower[a])/spacing[a])!=c[a];++n) p[a]=std::nextafter(p[a],center);
                if(std::floor((p[a]-lower[a])/spacing[a])!=c[a]) return false;
            }
            if(!mask || !finite(p) || !is_fluid(cell(p))) return false;
        }
        return remaining==0;
    }
};

struct Particle { Vec position{}, velocity{}, force{}; };

// Células com lado >= cutoff. Limitar a grade a O(N) evita alocações
// gigantes para raios pequenos; a busca ainda examina todos os vizinhos.
struct NeighborGrid {
    Cell dims{};
    Vec lower{}, width{};
    std::vector<int> head,next;
    explicit NeighborGrid(const Geometry& g,double cutoff,std::size_t n): lower(g.lower),next(n,-1) {
        auto e=g.extent(); int cap=std::max(1,static_cast<int>(std::ceil(std::sqrt(double(n)))));
        std::size_t count=1;
        for(int a=0;a<2;++a) {
            dims[a]=static_cast<int>(std::max(1.0,std::min(double(cap),std::floor(e[a]/cutoff))));
            width[a]=e[a]/dims[a]; count*=dims[a];
        }
        head.resize(count,-1);
    }
    int index(const Cell& c) const { return c[0]+dims[0]*c[1]; }
    Cell cell(const Vec& p) const {
        Cell c{}; for(int a=0;a<2;++a) c[a]=std::clamp(static_cast<int>((p[a]-lower[a])/width[a]),0,dims[a]-1); return c;
    }
    void rebuild(const std::vector<Particle>& p) {
        std::fill(head.begin(),head.end(),-1);
        for(std::size_t i=0;i<p.size();++i) { int k=index(cell(p[i].position)); next[i]=head[k]; head[k]=static_cast<int>(i); }
    }
};
// Gerador determinístico a partir de (semente, partícula, passo, evento): o mesmo
// resultado com qualquer quantidade de threads.
inline std::uint64_t splitmix64(std::uint64_t x) {
    x+=0x9E3779B97F4A7C15ull; x=(x^(x>>30))*0xBF58476D1CE4E5B9ull; x=(x^(x>>27))*0x94D049BB133111EBull; return x^(x>>31);
}
inline double unit_open(std::uint64_t h) { return (double((h>>11)+1))/9007199254740993.0; }  // (0,1)

struct Simulation {
    Config config;
    Geometry geometry;
    int n=0;                                   // total de partículas (A + B)
    std::vector<Particle> particles;
    std::vector<unsigned char> species;        // 0 = A, 1 = B
    std::array<double,2> masses{}, sigmas{};
    NeighborGrid grid;
    double potential=0;
    long long steps_done=0;                    // passos após t = 0 (a equilibração não conta)
    double boundary=0;                         // comprimento das superfícies sólidas
    // Acumuladores desde o último quadro e totais
    double impulse_walls=0, impulse_piston=0, accumulated_time=0;
    std::array<double,4> wall_heat{};          // energia recebida pelo gás em cada parede térmica (acumulada)
    double piston_work=0;                      // trabalho realizado pelo pistão sobre o gás (acumulado)

    Simulation(Config c,Geometry g):config(std::move(c)),geometry(std::move(g)),
        n(config.particles+config.particles_b),particles(n),species(n,0),
        grid(geometry,config.interaction_radius(),std::size_t(config.particles+config.particles_b)) {
        config.validate();
        if(config.threads>0) omp_set_num_threads(config.threads);
        omp_set_dynamic(0);
        for(int i=config.particles;i<n;++i) species[i]=1;
        masses={config.mass,config.mass_of_b()}; sigmas={config.sigma,config.sigma_of_b()};
        boundary=geometry.boundary_length();
        initialize(); calculate_forces();
        if(config.equilibration_steps>0) equilibrate();
        if(config.monoenergetic) make_monoenergetic();
    }
    double mass_of(int i) const { return masses[species[i]]; }
    double fraction_x(double f) const { return geometry.lower[0]+f*geometry.extent()[0]; }
    double initial_lower() const { return fraction_x(config.initial_x_min); }
    double initial_upper() const { return fraction_x(config.initial_x_max); }
    std::array<double,2> range_of(int i) const {
        return species[i] ? std::array<double,2>{fraction_x(config.initial_b_x_min),fraction_x(config.initial_b_x_max)}
                          : std::array<double,2>{initial_lower(),initial_upper()};
    }
    // --- pistão ------------------------------------------------------------
    double time() const { return steps_done*config.dt; }
    double piston_x(double t) const {
        const double x0=fraction_x(config.piston_x0), x1=fraction_x(config.piston_x1);
        if(t<=config.piston_start) return x0;
        const double travel=config.piston_speed*(t-config.piston_start);
        return x1>=x0 ? std::min(x1,x0+travel) : std::max(x1,x0-travel);
    }
    double gas_area() const {
        return config.has_piston() ? geometry.free_area_left_of(piston_x(time())) : geometry.free_area_left_of(1e300);
    }

    // Equilibração antes de t = 0: dinâmica confinada à faixa inicial de cada espécie,
    // paredes especulares e reescala das velocidades para a temperatura alvo a cada passo.
    void equilibrate() {
        const double target=n*config.boltzmann*config.temperature;  // K alvo (2 graus de liberdade)
        for(int s=0;s<config.equilibration_steps;++s) {
            step(true);
            const double k=kinetic(), scale=k>0 ? std::sqrt(target/k) : 0;
            #pragma omp parallel for schedule(static)
            for(int i=0;i<n;++i) for(int a=0;a<2;++a) particles[i].velocity[a]*=scale;
        }
        impulse_walls=impulse_piston=accumulated_time=0;
    }
    // Todas as partículas com a mesma energia cinética k T (mesmo |v| por espécie), direções aleatórias.
    void make_monoenergetic() {
        for(int i=0;i<n;++i) {
            auto& v=particles[i].velocity;
            const double speed=std::sqrt(2*config.boltzmann*config.temperature/mass_of(i)), norm=std::sqrt(norm2(v));
            if(norm>0) { for(int a=0;a<2;++a) v[a]*=speed/norm; }
            else {
                const double angle=2*std::acos(-1.0)*unit_open(splitmix64(config.seed^(0xABCDull+i)));
                v={speed*std::cos(angle),speed*std::sin(angle)};
            }
        }
    }

    // --- condição inicial --------------------------------------------------
    // Amostrador uniforme na área livre de uma faixa [x_min, x_max).
    struct Sampler {
        std::vector<std::size_t> free; std::vector<double> weights,left,right;
        std::discrete_distribution<std::size_t> pick;
        double x_min=0,x_max=0;
    };
    Sampler make_sampler(double x_min,double x_max) const {
        Sampler s; s.x_min=x_min; s.x_max=x_max;
        require(x_max>x_min,"A região inicial é pequena demais para a precisão das coordenadas.");
        for(std::size_t i=0;i<geometry.fluid.size();++i) if(geometry.fluid[i]) {
            const int x=static_cast<int>(i%geometry.dims[0]);
            double lo=std::max(x_min,geometry.lower[0]+x*geometry.spacing[0]);
            double hi=std::min(x_max,geometry.lower[0]+(x+1)*geometry.spacing[0]);
            if(hi>lo) {
                require(std::nextafter(lo,hi)<=std::nextafter(hi,lo),
                        "Interseção inicial pequena demais para a precisão numérica; ajuste seus limites.");
                // A altura é constante. Ponderar pela largura da interseção
                // mantém densidade uniforme mesmo se o corte atravessar células.
                s.free.push_back(i); s.left.push_back(lo); s.right.push_back(hi);
                s.weights.push_back((hi-lo)/geometry.spacing[0]);
            }
        }
        require(!s.free.empty(),"A região inicial selecionada não contém área livre.");
        s.pick=std::discrete_distribution<std::size_t>(s.weights.begin(),s.weights.end());
        return s;
    }
    Vec sample(Sampler& s,std::mt19937_64& rng) const {
        std::uniform_real_distribution<double> uniform(0,1);
        const auto sel=s.pick(rng); const auto idx=s.free[sel];
        Cell c{int(idx%geometry.dims[0]),int(idx/geometry.dims[0])};
        Vec p{};
        for(int a=0;a<2;++a) {
            const double u=std::clamp(uniform(rng),1e-9,1-1e-9);
            p[a]=geometry.lower[a]+(c[a]+u)*geometry.spacing[a];
            if(a==0) p[a]=std::clamp(s.left[sel]+u*(s.right[sel]-s.left[sel]),
                                     std::nextafter(s.left[sel],s.right[sel]),std::nextafter(s.right[sel],s.left[sel]));
        }
        return p;
    }
    void initialize() {
        std::mt19937_64 rng(config.seed);
        std::normal_distribution<double> normal(0,1);
        std::array<Sampler,2> samplers{make_sampler(initial_lower(),initial_upper()),
                                       make_sampler(fraction_x(config.initial_b_x_min),fraction_x(config.initial_b_x_max))};
        if(config.min_distance>0) place_separated(samplers,rng);
        else for(int i=0;i<n;++i) particles[i].position=sample(samplers[species[i]],rng);
        for(int i=0;i<n;++i) {
            auto& p=particles[i];
            const double s=std::sqrt(config.boltzmann*config.temperature/mass_of(i));
            for(int a=0;a<2;++a) p.velocity[a]=s*normal(rng);
            const auto r=range_of(i);
            require(p.position[0]>=r[0] && p.position[0]<r[1],"Falha numérica na região inicial; aumente sua largura.");
            require(geometry.is_fluid(geometry.cell(p.position)),"Falha numérica ao posicionar partículas; reescale a geometria.");
        }
    }
    // Posições com distância mínima d entre quaisquer duas partículas.
    // 1) adsorção sequencial aleatória (uniforme em densidades baixas);
    // 2) se falhar, rede quadrada com espaçamento >= d e pequena perturbação aleatória.
    void place_separated(std::array<Sampler,2>& samplers,std::mt19937_64& rng) {
        const double d=config.min_distance, d2=d*d;
        const Vec lo=geometry.lower, ext=geometry.extent();
        Cell dims{};
        for(int a=0;a<2;++a) dims[a]=std::max(1,static_cast<int>(std::min(4096.0,std::floor(ext[a]/d))));
        Vec width{ext[0]/dims[0],ext[1]/dims[1]};
        std::vector<std::vector<int>> cells(static_cast<std::size_t>(dims[0])*dims[1]);
        auto cell_of=[&](const Vec& p) {
            Cell c{}; for(int a=0;a<2;++a) c[a]=std::clamp(static_cast<int>((p[a]-lo[a])/width[a]),0,dims[a]-1); return c;
        };
        auto fits=[&](const Vec& p) {
            Cell c=cell_of(p);
            for(int y=std::max(0,c[1]-1);y<=std::min(dims[1]-1,c[1]+1);++y)
            for(int x=std::max(0,c[0]-1);x<=std::min(dims[0]-1,c[0]+1);++x)
            for(int j:cells[std::size_t(x)+std::size_t(dims[0])*y]) {
                Vec r{p[0]-particles[j].position[0],p[1]-particles[j].position[1]};
                if(norm2(r)<d2) return false;
            }
            return true;
        };
        auto add=[&](int i,const Vec& p) {
            particles[i].position=p; Cell c=cell_of(p); cells[std::size_t(c[0])+std::size_t(dims[0])*c[1]].push_back(i);
        };
        bool ok=true;
        for(int i=0;i<n && ok;++i) {
            ok=false;
            for(int attempt=0;attempt<2000;++attempt) {
                Vec p=sample(samplers[species[i]],rng); if(fits(p)) { add(i,p); ok=true; break; }
            }
        }
        if(ok) return;
        // Rede quadrada por espécie: maior espaçamento com pontos suficientes na faixa inicial.
        for(auto& c:cells) c.clear();
        for(int s=0;s<2;++s) {
            std::vector<int> members; for(int i=0;i<n;++i) if(species[i]==s) members.push_back(i);
            if(members.empty()) continue;
            const double x_min=samplers[s].x_min, x_max=samplers[s].x_max;
            double area=0; for(double w:samplers[s].weights) area+=w*geometry.spacing[0]*geometry.spacing[1];
            auto inside=[&](const Vec& p) { return p[0]>=x_min && p[0]<x_max && geometry.is_fluid(geometry.cell(p)); };
            std::vector<Vec> sites; bool placed=false;
            for(double a=std::sqrt(area/members.size());a>=d && !placed;a*=0.98) {
                sites.clear();
                for(double y=lo[1]+0.5*a;y<lo[1]+ext[1];y+=a)
                for(double x=x_min+0.5*a;x<x_max;x+=a) { Vec p{x,y}; if(inside(p) && fits(p)) sites.push_back(p); }
                if(sites.size()>=members.size()) {
                    std::shuffle(sites.begin(),sites.end(),rng);
                    std::uniform_real_distribution<double> jitter(-0.5*(a-d),0.5*(a-d));
                    for(std::size_t k=0;k<members.size();++k) {
                        Vec p{sites[k][0]+jitter(rng),sites[k][1]+jitter(rng)};
                        if(!inside(p)) p=sites[k];
                        add(members[k],p);
                    }
                    placed=true;
                }
            }
            if(!placed) throw std::runtime_error("Densidade alta demais para a distância mínima inicial: reduza o número de "
                                                 "partículas, sigma/min_distance, ou aumente a região inicial.");
        }
    }

    // --- interação ----------------------------------------------------------
    // Força radial (F = f * r_vetor) e energia de um par a distância² r2 < rc².
    struct PairTerms { double f, u; };
    PairTerms pair_terms(double r2,double sigma=-1) const {
        switch(config.potential) {
            case Potential::Coulomb: {
                const double eps2=config.softening*config.softening, rc2=config.cutoff*config.cutoff;
                const double coupling=config.coulomb_constant*config.charge*config.charge;
                const double inv=1/std::sqrt(r2+eps2);
                return {coupling*inv*inv*inv, coupling*(inv-1/std::sqrt(rc2+eps2))};
            }
            case Potential::WCA: case Potential::LJ: {
                if(sigma<=0) sigma=config.sigma;
                const double s2=sigma*sigma/r2, s6=s2*s2*s2, e=config.epsilon;
                if(config.potential==Potential::WCA) {
                    if(r2>=std::pow(2.0,1.0/3.0)*sigma*sigma) return {0,0};
                    return {24*e*(2*s6*s6-s6)/r2, 4*e*(s6*s6-s6)+e};   // U(2^(1/6) sigma) = 0
                }
                const double rc=config.lj_cutoff*sigma;
                if(r2>=rc*rc) return {0,0};
                const double c2=1/(config.lj_cutoff*config.lj_cutoff), c6=c2*c2*c2;
                return {24*e*(2*s6*s6-s6)/r2, 4*e*(s6*s6-s6)-4*e*(c6*c6-c6)};
            }
            default: return {0,0};
        }
    }
    bool interacting() const {
        switch(config.potential) {
            case Potential::Coulomb: return config.coulomb_constant*config.charge*config.charge!=0;
            case Potential::WCA: case Potential::LJ: return config.epsilon!=0;
            default: return false;
        }
    }
    void calculate_forces() {
        grid.rebuild(particles);
        const double rc=config.interaction_radius(), rc2=rc*rc;
        const bool singular_at_zero=config.potential!=Potential::Coulomb || config.softening==0;
        const bool active=interacting();
        double total=0; int bad=0;
        // Cada thread escreve apenas a força da própria partícula. O par é
        // calculado duas vezes para evitar atomics/data races; U leva fator 1/2.
        #pragma omp parallel for schedule(static) reduction(+:total) reduction(|:bad)
        for(int i=0;i<n;++i) {
            Vec force{}; double energy=0;
            if(active) {
                Cell c=grid.cell(particles[i].position);
                for(int y=std::max(0,c[1]-1);y<=std::min(grid.dims[1]-1,c[1]+1);++y)
                for(int x=std::max(0,c[0]-1);x<=std::min(grid.dims[0]-1,c[0]+1);++x)
                for(int j=grid.head[grid.index({x,y})];j!=-1;j=grid.next[j]) {
                    if(i==j) continue;
                    Vec d{}; for(int a=0;a<2;++a) d[a]=particles[i].position[a]-particles[j].position[a];
                    double r2=norm2(d); if(r2>=rc2) continue;
                    if(r2==0 && singular_at_zero) { bad=1; continue; }
                    auto t=pair_terms(r2,0.5*(sigmas[species[i]]+sigmas[species[j]]));
                    for(int a=0;a<2;++a) force[a]+=t.f*d[a];
                    energy+=t.u;
                }
            }
            particles[i].force=force; total+=0.5*energy;
            if(!finite(force) || !std::isfinite(energy)) bad=1;
        }
        require(!bad && std::isfinite(total),"Força singular/não finita. Aumente softening ou reescale os parâmetros.");
        potential=total;
    }

    // --- integração -----------------------------------------------------------
    // confine: equilibração (paredes temporárias na faixa inicial, paredes externas especulares, pistão parado).
    void step(bool confine=false) {
        int bad=0;
        const double dt=config.dt, kB=config.boltzmann;
        const bool piston=config.has_piston() && !confine;
        const double t0=time(), xp=piston ? piston_x(t0+dt) : 0, up=piston ? (piston_x(t0+dt)-piston_x(t0))/dt : 0;
        const auto wall_t=config.wall_temperature;
        const std::uint64_t seed=config.seed;
        const long long stepno=steps_done;
        double imp_w=0, imp_p=0, heat0=0, heat1=0, heat2=0, heat3=0, work=0;
        #pragma omp parallel for schedule(static) reduction(|:bad) reduction(+:imp_w,imp_p,heat0,heat1,heat2,heat3,work)
        for(int i=0;i<n;++i) {
            auto& p=particles[i];
            const double m=mass_of(i), kick=0.5*dt/m;
            for(int a=0;a<2;++a) p.velocity[a]+=kick*p.force[a];
            const Vec old=p.position;
            std::uint64_t event=0;
            double heat[4]{};
            auto bounce=[&](int a,int sign,int wall,Vec& v) {
                const double vn=v[a];
                if(!confine && wall<4 && wall_t[wall]>0) {
                    // Parede difusiva: componente normal com a distribuição do fluxo
                    // (v exp(-m v²/2kT)), tangencial gaussiana, ambas na temperatura da parede.
                    const double e0=norm2(v), s=std::sqrt(kB*wall_t[wall]/m);
                    std::uint64_t h=splitmix64(seed^splitmix64(std::uint64_t(i)*0x9E3779B97F4A7C15ull^splitmix64(stepno*1315423911ull+event++)));
                    const double u1=unit_open(h), u2=unit_open(h=splitmix64(h)), u3=unit_open(splitmix64(h));
                    v[a]=-sign*s*std::sqrt(-2*std::log(u1));
                    v[1-a]=s*std::sqrt(-2*std::log(u2))*std::cos(2*std::acos(-1.0)*u3);
                    heat[wall]+=0.5*m*(norm2(v)-e0);
                }
                else v[a]=-v[a];
                imp_w+=m*std::abs(v[a]-vn);
            };
            if(!geometry.drift(p.position,p.velocity,dt,bounce)) bad=1;
            heat0+=heat[0]; heat1+=heat[1]; heat2+=heat[2]; heat3+=heat[3];
            if(confine) {
                const auto r=range_of(i);
                if(p.position[0]<r[0] || p.position[0]>=r[1]) {
                    // Reflexão especular no plano; se cair num sólido, volta à posição anterior.
                    const double plane=p.position[0]<r[0] ? r[0] : r[1];
                    Vec q{2*plane-p.position[0],p.position[1]};
                    if(q[0]>=r[0] && q[0]<r[1] && geometry.is_fluid(geometry.cell(q))) p.position=q;
                    else p.position=old;
                    p.velocity[0]=-p.velocity[0];
                }
            }
            if(piston && p.position[0]>=xp) {
                // Colisão elástica com o pistão em movimento: no referencial do pistão, reflexão especular.
                const double v0=p.velocity[0];
                p.velocity[0]=2*up-v0;
                Vec q{2*xp-p.position[0],p.position[1]};
                if(q[0]<xp && geometry.is_fluid(geometry.cell(q))) p.position=q;
                else p.position={std::min(old[0],std::nextafter(xp,-1e300)),old[1]};
                if(!geometry.is_fluid(geometry.cell(p.position))) bad=1;
                imp_p+=m*(v0-p.velocity[0]);
                work+=0.5*m*(p.velocity[0]*p.velocity[0]-v0*v0);
            }
        }
        require(!bad,"Falha na trajetória/colisão: reduza dt ou reescale os parâmetros.");
        if(!confine) {
            ++steps_done; accumulated_time+=dt; impulse_walls+=imp_w; impulse_piston+=imp_p;
            wall_heat[0]+=heat0; wall_heat[1]+=heat1; wall_heat[2]+=heat2; wall_heat[3]+=heat3; piston_work+=work;
        }
        calculate_forces();
        #pragma omp parallel for schedule(static) reduction(|:bad)
        for(int i=0;i<n;++i) {
            auto& p=particles[i]; const double kick=0.5*dt/mass_of(i);
            for(int a=0;a<2;++a) p.velocity[a]+=kick*p.force[a];
            if(!finite(p.velocity)) bad=1;
        }
        require(!bad,"Velocidade não finita; reduza dt ou reescale os parâmetros.");
    }
    double kinetic() const {
        double k=0;
        #pragma omp parallel for reduction(+:k)
        for(int i=0;i<n;++i) k+=0.5*mass_of(i)*norm2(particles[i].velocity);
        require(std::isfinite(k),"Energia cinética não finita."); return k;
    }

    // --- saída -----------------------------------------------------------------
    static void write_vec(std::ostream& out,const Vec& v) { out<<'['<<v[0]<<','<<v[1]<<']'; }
    static void write_opt(std::ostream& out,double v) { if(v>0) out<<v; else out<<"null"; }
    void metadata(std::ostream& out) const {
        out<<std::setprecision(17)<<"{\"type\":\"metadata\",\"version\":2,\"spatial_dimension\":2,\"particles\":"<<n
           <<",\"particles_b\":"<<config.particles_b
           <<",\"steps\":"<<config.steps<<",\"dt\":"<<config.dt<<",\"target_temperature\":"<<config.temperature
           <<",\"boltzmann\":"<<config.boltzmann<<",\"mass\":"<<config.mass<<",\"masses\":["<<masses[0]<<','<<masses[1]<<']'
           <<",\"potential\":\""<<potential_name(config.potential)<<"\",\"sigma\":"<<config.sigma
           <<",\"sigmas\":["<<sigmas[0]<<','<<sigmas[1]<<']'
           <<",\"epsilon\":"<<config.epsilon<<",\"interaction_radius\":"<<config.interaction_radius()
           <<",\"velocity_distribution\":\""<<(config.monoenergetic ? "mono" : "maxwell")<<"\""
           <<",\"boundary_length\":"<<boundary<<",\"wall_temperatures\":[";
        for(int w=0;w<4;++w) { if(w) out<<','; write_opt(out,config.wall_temperature[w]); }
        out<<"],\"piston\":";
        if(config.has_piston()) out<<"{\"x0\":"<<fraction_x(config.piston_x0)<<",\"x1\":"<<fraction_x(config.piston_x1)
                                   <<",\"speed\":"<<config.piston_speed<<",\"start\":"<<config.piston_start<<'}';
        else out<<"null";
        out<<",\"dims\":["<<geometry.dims[0]<<','<<geometry.dims[1]<<"],\"lower\":";
        write_vec(out,geometry.lower); out<<",\"spacing\":"; write_vec(out,geometry.spacing);
        if(config.particles_b>0) {
            out<<",\"species\":[";
            for(int i=0;i<n;++i) { if(i) out<<','; out<<int(species[i]); }
            out<<']';
        }
        out<<",\"solid_indices\":["; bool comma=false;
        for(std::size_t i=0;i<geometry.fluid.size();++i) if(!geometry.fluid[i]) { if(comma) out<<','; out<<i; comma=true; }
        out<<"]}\n"<<std::flush;
    }
    // Pressão média desde o quadro anterior: impulso transferido às paredes (ou ao pistão)
    // dividido pelo comprimento da superfície e pelo intervalo de tempo.
    void frame(std::ostream& out,int step) {
        double k=kinetic(),t=2*k/(2.0*n*config.boltzmann);
        require(std::isfinite(t) && std::isfinite(k+potential),"Diagnóstico não finito.");
        out<<std::setprecision(17)<<"{\"type\":\"frame\",\"step\":"<<step<<",\"time\":"<<step*config.dt<<",\"temperature\":"<<t
           <<",\"kinetic\":"<<k<<",\"potential\":"<<potential<<",\"pressure\":";
        if(accumulated_time>0) {
            // Com pistão: paredes à esquerda do pistão + a face do pistão (altura da caixa).
            const double length=config.has_piston() ? geometry.boundary_length(piston_x(time()))+geometry.extent()[1] : boundary;
            out<<(impulse_walls+impulse_piston)/(length*accumulated_time);
        }
        else out<<"null";
        out<<",\"area\":"<<gas_area()<<",\"wall_heat\":["<<wall_heat[0]<<','<<wall_heat[1]<<','<<wall_heat[2]<<','<<wall_heat[3]<<']'
           <<",\"piston\":";
        if(config.has_piston()) out<<"{\"x\":"<<piston_x(time())<<",\"work\":"<<piston_work<<'}'; else out<<"null";
        impulse_walls=impulse_piston=accumulated_time=0;
        out<<",\"positions\":[";
        for(std::size_t i=0;i<particles.size();++i) { if(i) out<<','; write_vec(out,particles[i].position); }
        out<<"],\"velocities\":[";
        for(std::size_t i=0;i<particles.size();++i) { if(i) out<<','; write_vec(out,particles[i].velocity); }
        out<<"]}\n"<<std::flush;
    }
};
} // namespace md
