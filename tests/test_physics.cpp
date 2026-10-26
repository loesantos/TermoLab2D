#include "md.hpp"
#include <functional>

void check(bool ok,const std::string& message) { if(!ok) throw std::runtime_error(message); }
void near(double got,double want,double tolerance,const std::string& message) {
    check(std::isfinite(got) && std::abs(got-want)<=tolerance,message+": obtido="+std::to_string(got)+", esperado="+std::to_string(want));
}
md::Geometry box(md::Cell dims={20,20},md::Vec spacing={1,1},md::Vec origin={0,0}) {
    md::Geometry g; g.dims=dims; g.spacing=spacing; g.lower=origin;
    g.fluid.assign(std::size_t(dims[0])*dims[1],1); return g;
}
md::Config config(int n) { md::Config c; c.geometry="test.vtk"; c.particles=n; c.threads=2; return c; }
void test_force() {
    auto c=config(2); c.cutoff=5; c.softening=0; c.mass=2;
    md::Simulation s(c,box());
    s.particles[0].position={8,10}; s.particles[1].position={10,10}; s.calculate_forces();
    near(s.particles[0].force[0],-0.25,1e-14,"Força coulombiana repulsiva");
    near(s.particles[1].force[0],0.25,1e-14,"Terceira lei de Newton");
    near(s.potential,0.5-0.2,1e-14,"Potencial deslocado no corte");
    s.particles[1].position={13,10}; s.calculate_forces();
    near(md::norm2(s.particles[0].force),0,0,"Exclusão no raio de corte");
    s.config.softening=0.5; s.particles[1].position={10,10}; s.calculate_forces();
    near(s.particles[0].force[0],-2/std::pow(4.25,1.5),1e-14,"Regularização");
    s.particles[1].position=s.particles[0].position; s.calculate_forces();
    near(md::norm2(s.particles[0].force),0,0,"Sobreposição regularizada");
    s.config.softening=0;
    bool failed=false; try { s.calculate_forces(); } catch(const std::exception&) { failed=true; }
    check(failed,"Sobreposição singular deve falhar");
}
void test_neighbors() {
    for(double radius:{0.2,2.7,100.0}) {
        auto c=config(220); c.cutoff=radius;
        md::Simulation s(c,box({20,13},{0.7,1.3},{-4,2}));
        for(int i=0;i<c.particles;++i) {
            md::Vec f{};
            for(int j=0;j<c.particles;++j) if(i!=j) {
                md::Vec d{}; for(int a=0;a<2;++a) d[a]=s.particles[i].position[a]-s.particles[j].position[a];
                double r2=md::norm2(d);
                if(r2<radius*radius) for(int a=0;a<2;++a) f[a]+=d[a]/std::pow(r2+c.softening*c.softening,1.5);
            }
            for(int a=0;a<2;++a) near(s.particles[i].force[a],f[a],1e-10,"Células versus todos os pares");
        }
        auto reference=s.particles;
        omp_set_num_threads(4); s.calculate_forces();
        for(int i=0;i<c.particles;++i) for(int a=0;a<2;++a)
            near(s.particles[i].force[a],reference[i].force[a],0,"Independência da quantidade de threads");
    }
}
void test_maxwell() {
    auto c=config(60000); c.charge=0; c.temperature=2; c.mass=3; c.boltzmann=4;
    md::Simulation s(c,box());
    double variance=c.boltzmann*c.temperature/c.mass;
    for(int a=0;a<2;++a) {
        double sum=0,squares=0,fourth=0;
        for(const auto& p:s.particles) { double v=p.velocity[a]; sum+=v; squares+=v*v; fourth+=v*v*v*v; }
        near(sum/c.particles,0,0.025,"Média gaussiana");
        near(squares/c.particles,variance,0.04*variance,"Variância kBT/m");
        near(fourth/c.particles,3*variance*variance,0.10*variance*variance,"Quarto momento gaussiano");
    }
    double speed=0; for(const auto& p:s.particles) speed+=std::sqrt(md::norm2(p.velocity));
    near(speed/c.particles,std::sqrt(variance*std::acos(-1)/2),0.02,"Média Rayleigh do módulo da velocidade em 2D");
    near(s.kinetic()/(c.particles*c.boltzmann),c.temperature,0.03,"Temperatura com dois graus de liberdade");
    c.particles=5; c.temperature=0; md::Simulation cold(c,box());
    near(cold.kinetic(),0,0,"Temperatura zero");
}
void test_collisions() {
    auto g=box({10,3});
    for(int y=0;y<3;++y) g.fluid[g.index({5,y})]=0;
    md::Vec p{4.5,1.5},v{20,0};
    check(g.drift(p,v,0.1),"Colisão com parede fina"); near(p[0],3.5,1e-11,"Sem tunelamento"); near(v[0],-20,0,"Reflexão especular");
    auto b=box({2,2},{1,1},{-1,-1});
    p={0,0}; v={101,0}; check(b.drift(p,v,1),"Múltiplas reflexões");
    near(p[0],1,1e-10,"Posição após múltiplas reflexões"); near(v[0],-101,0,"Reflexão no instante final");
    p={0,0}; v={0,0}; check(b.drift(p,v,10),"Partícula em repouso");
    auto corner=box({3,3}); corner.fluid[corner.index({1,1})]=0;
    p={0.5,0.5}; v={1,1}; check(corner.drift(p,v,1),"Colisão diagonal");
    near(p[0],0.5,1e-11,"Reflexão diagonal x"); near(p[1],0.5,1e-11,"Reflexão diagonal y");
    auto anisotropic=box({11,13},{0.5,0.7},{-3.5,2.2});
    std::mt19937_64 rng(17); std::normal_distribution<double> normal(0,20);
    p={-3.2,3.7};
    for(int i=0;i<1000;++i) {
        v={normal(rng),normal(rng)}; double speed2=md::norm2(v);
        check(anisotropic.drift(p,v,0.3),"Trajetória aleatória em geometria anisotrópica");
        check(anisotropic.is_fluid(anisotropic.cell(p)),"Partícula permanece em fluido");
        near(md::norm2(v),speed2,1e-10,"Colisão conserva energia cinética");
    }
}
void test_integration() {
    auto c=config(2); c.cutoff=20; c.softening=0.1; c.dt=0.0005;
    md::Simulation s(c,box({40,40}));
    s.particles[0].position={19,20}; s.particles[1].position={21,20};
    s.particles[0].velocity={0,0.1}; s.particles[1].velocity={0,-0.1}; s.calculate_forces();
    double e0=s.kinetic()+s.potential;
    for(int i=0;i<3000;++i) s.step();
    near(s.kinetic()+s.potential,e0,1e-7,"Conservação de energia Verlet");
    for(int a=0;a<2;++a) near(s.particles[0].velocity[a]+s.particles[1].velocity[a],0,1e-12,"Conservação de momento");
}
void test_short_range() {
    auto c=config(2); c.potential=md::Potential::LJ; c.sigma=0.5; c.epsilon=2; c.lj_cutoff=2.5;
    md::Simulation s(c,box());
    const double r=0.7, sr6=std::pow(c.sigma/r,6), rc6=std::pow(1/c.lj_cutoff,6);
    s.particles[0].position={8,10}; s.particles[1].position={8+r,10}; s.calculate_forces();
    near(s.particles[1].force[0],24*c.epsilon*(2*sr6*sr6-sr6)/r,1e-12,"Força Lennard-Jones");
    near(s.particles[0].force[0],-s.particles[1].force[0],1e-12,"Terceira lei (LJ)");
    near(s.potential,4*c.epsilon*(sr6*sr6-sr6)-4*c.epsilon*(rc6*rc6-rc6),1e-12,"Potencial LJ deslocado");
    s.particles[1].position={8+0.8,10}; s.calculate_forces();
    check(s.particles[1].force[0]<0,"LJ atrativo além do mínimo");
    s.particles[1].position={8+2.5*c.sigma+1e-9,10}; s.calculate_forces();
    near(md::norm2(s.particles[1].force),0,0,"Corte LJ");
    s.config.potential=md::Potential::WCA;
    s.particles[1].position={8+1.3*c.sigma,10}; s.calculate_forces();
    near(md::norm2(s.particles[1].force),0,0,"WCA sem atração além de 2^(1/6) sigma");
    near(s.potential,0,0,"Energia WCA nula além do corte");
    s.particles[1].position={8+c.sigma,10}; s.calculate_forces();
    near(s.potential,c.epsilon,1e-12,"U_WCA(sigma) = epsilon");
    check(s.particles[1].force[0]>0,"WCA repulsivo");
    s.config.potential=md::Potential::None; s.calculate_forces();
    near(md::norm2(s.particles[1].force)+std::abs(s.potential),0,0,"Sem interação");
    // conservação de energia com LJ
    auto e=config(200); e.potential=md::Potential::LJ; e.sigma=0.3; e.min_distance=std::pow(2.0,1.0/6)*e.sigma;
    md::Simulation m(e,box({10,10}));
    double e0=m.kinetic()+m.potential;
    for(int i=0;i<2000;++i) m.step();
    near(m.kinetic()+m.potential,e0,2e-3*std::abs(e0),"Conservação de energia LJ");
}
void test_min_distance() {
    for(int n:{300,1100}) {   // 1100 excede o bloqueio da adsorção aleatória: usa a rede quadrada
        auto c=config(n); c.charge=0; c.min_distance=0.4; c.initial_x_max=0.5;
        md::Simulation s(c,box());
        double closest=1e9;
        for(int i=0;i<n;++i) for(int j=i+1;j<n;++j) {
            md::Vec d{s.particles[i].position[0]-s.particles[j].position[0],s.particles[i].position[1]-s.particles[j].position[1]};
            closest=std::min(closest,std::sqrt(md::norm2(d)));
        }
        check(closest>=c.min_distance,"Distância mínima inicial: "+std::to_string(closest));
        for(auto& p:s.particles) check(p.position[0]<10,"Posição dentro da faixa inicial");
    }
    auto c=config(5000); c.charge=0; c.min_distance=0.4; c.initial_x_max=0.5;
    bool failed=false; try { md::Simulation s(c,box()); } catch(const std::exception&) { failed=true; }
    check(failed,"Densidade impossível deve falhar");
}
void test_equilibration() {
    auto c=config(400); c.potential=md::Potential::WCA; c.sigma=0.3; c.min_distance=0.34;
    c.initial_x_max=0.5; c.temperature=1.5; c.equilibration_steps=2000;
    md::Simulation s(c,box());
    for(auto& p:s.particles) check(p.position[0]<10,"Equilibração confinada à faixa inicial");
    near(s.kinetic()/c.particles,c.temperature,1e-9,"Temperatura reescalada na equilibração");
}
void test_ideal_pressure() {
    // Gás sem interação: P = N k T / A medido pelo impulso nas paredes.
    auto c=config(4000); c.potential=md::Potential::None; c.steps=0;
    md::Simulation s(c,box({20,20}));
    for(int i=0;i<30000;++i) s.step();
    double p=(s.impulse_walls)/(s.boundary*s.accumulated_time);
    double ideal=c.particles*c.boltzmann*(s.kinetic()/(c.particles*c.boltzmann))/400.0;
    near(p,ideal,0.03*ideal,"Pressão de gás ideal nas paredes");
    near(s.boundary,80,1e-12,"Perímetro da caixa");
    near(s.geometry.boundary_length(10.0),40,1e-12,"Perímetro à esquerda de x = 10");
}
void test_thermal_wall() {
    // Partículas sem interação numa caixa com todas as paredes a T = 3: o gás termaliza em 3
    // e a energia ganha é igual ao calor recebido.
    auto c=config(3000); c.potential=md::Potential::None; c.temperature=0.5; c.dt=0.002;
    c.wall_temperature={3,3,3,3};
    md::Simulation s(c,box({10,10}));
    const double e0=s.kinetic();
    for(int i=0;i<20000;++i) s.step();
    near(s.kinetic()/c.particles,3,0.15,"Termalização pelas paredes");
    double q=0; for(double h:s.wall_heat) q+=h;
    near(s.kinetic()-e0,q,1e-6*std::abs(q),"Energia ganha = calor das paredes");
}
void test_piston() {
    // Compressão rápida de um gás sem interação: energia ganha = trabalho do pistão; nada além do pistão.
    auto c=config(1000); c.potential=md::Potential::None; c.piston_x0=1; c.piston_x1=0.5; c.piston_speed=2;
    md::Simulation s(c,box({20,10}));
    const double e0=s.kinetic();
    for(int i=0;i<8000;++i) {
        s.step();
        const double xp=s.piston_x(s.time());
        for(const auto& p:s.particles) check(p.position[0]<xp,"Partícula além do pistão");
    }
    near(s.piston_x(s.time()),10,1e-12,"Pistão parado na posição final");
    check(s.kinetic()>e0,"Compressão aquece o gás");
    near(s.kinetic()-e0,s.piston_work,1e-9*s.piston_work,"Energia ganha = trabalho do pistão");
    near(s.gas_area(),100,1e-9,"Área do gás à esquerda do pistão");
}
void test_species_and_mono() {
    auto c=config(300); c.particles_b=200; c.mass_b=4; c.charge=0; c.initial_x_max=0.5; c.initial_b_x_min=0.5;
    c.monoenergetic=true; c.temperature=2;
    md::Simulation s(c,box());
    check(s.n==500,"Total de partículas");
    for(int i=0;i<s.n;++i) {
        const auto& p=s.particles[i];
        check(s.species[i] ? p.position[0]>=10 : p.position[0]<10,"Faixa inicial por espécie");
        near(0.5*s.mass_of(i)*md::norm2(p.velocity),c.boltzmann*c.temperature,1e-9,"Energia cinética monoenergética");
    }
    near(s.kinetic()/(s.n*c.boltzmann),c.temperature,1e-9,"Temperatura monoenergética");
}
int main() {
    try {
        for(auto test:std::vector<std::pair<std::string,std::function<void()>>>{{"força",test_force},{"vizinhos/OpenMP",test_neighbors},{"Maxwell",test_maxwell},{"colisões",test_collisions},{"integração",test_integration},
            {"WCA/LJ",test_short_range},{"distância mínima",test_min_distance},{"equilibração",test_equilibration},
            {"pressão",test_ideal_pressure},{"parede térmica",test_thermal_wall},{"pistão",test_piston},
            {"espécies/monoenergético",test_species_and_mono}}) {
            test.second(); std::cout<<"OK: "<<test.first<<'\n';
        }
        return 0;
    } catch(const std::exception& e) { std::cerr<<"FALHOU: "<<e.what()<<'\n'; return 1; }
}
