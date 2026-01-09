class Student {

    String name;
    int age;
    long phno = 9345L;
    char c = 'A';

    void display() {
        System.out.println("Name: " + name);
        System.out.println("Age: " + age);
        System.out.println("ph: " + phno);
        System.out.println("city: " + c);
    }
}

class Main {
    public static void main(String[] args) {

        Student s1 = new Student();
        s1.name = "Shahil";
        s1.age = 20;
        s1.phno = 9345L;
 
        s1.display();
    }
}
