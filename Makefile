CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -Wpedantic
OMPFLAGS = -fopenmp

.PHONY: all test clean run
all: build/simulator
build/simulator: src/main.cpp src/md.hpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $(OMPFLAGS) src/main.cpp -o $@
build/test_physics: tests/test_physics.cpp src/md.hpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $(OMPFLAGS) -Isrc tests/test_physics.cpp -o $@
test: build/simulator build/test_physics
	./build/test_physics
	MPLBACKEND=Agg python3 -m unittest discover -s tests -p 'test_*.py' -v
run: build/simulator
	python3 visualize.py examples/simulation.cfg
clean:
	rm -f build/simulator build/test_physics
